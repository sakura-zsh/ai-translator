//! Headless CLI binary (`ai-translator-cli`) sharing `ai-translator-core`.
//! Reads config read-only so it never clobbers concurrent GUI edits.

use std::io::{self, IsTerminal, Read};
use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Parser, ValueEnum};

use ai_translator_core::config::{AppConfig, ConfigStore, ImageMode, LlmProfile};
use ai_translator_core::ocr::OcrService;
use ai_translator_core::platform::{
    capture_region_wayland, read_clipboard_image_png, read_clipboard_text,
    read_primary_selection_text, send_notification, write_clipboard_text,
};
use ai_translator_core::presets::effective_extra_prompt;
use ai_translator_core::translator::Translator;

#[derive(Debug, Clone, ValueEnum)]
enum CliImageMode {
    Ocr,
    Vision,
}

impl From<CliImageMode> for ImageMode {
    fn from(m: CliImageMode) -> Self {
        match m {
            CliImageMode::Ocr => ImageMode::Ocr,
            CliImageMode::Vision => ImageMode::Vision,
        }
    }
}

#[derive(Debug, Parser)]
#[command(
    name = "ai-translator-cli",
    version,
    about = "AI 翻译器命令行模式：不启动图形界面完成翻译。",
    after_help = "示例：\n  ai-translator-cli \"Hello world\"\n  ai-translator-cli --clipboard -t ja\n  ai-translator-cli --clipboard --image\n  ai-translator-cli --screenshot --mode vision\n  echo 'text' | ai-translator-cli"
)]
struct Args {
    /// 要翻译的文本（省略则从标准输入读取）
    text: Vec<String>,

    /// 翻译剪贴板中的文本（可配合 --image 翻译剪贴板图片）
    #[arg(long)]
    clipboard: bool,

    /// 翻译鼠标选区（Linux Primary Selection，失败回落剪贴板）
    #[arg(long)]
    primary: bool,

    /// 翻译剪贴板中的图片
    #[arg(long)]
    image: bool,

    /// 截图后翻译（Linux Wayland: slurp + grim）
    #[arg(long, conflicts_with_all = ["clipboard", "primary", "image"])]
    screenshot: bool,

    /// 源语言代码（默认取配置）
    #[arg(short, long)]
    source: Option<String>,

    /// 目标语言代码（默认取配置）
    #[arg(short, long)]
    target: Option<String>,

    /// 图片翻译方式（默认取配置）
    #[arg(long, value_enum)]
    mode: Option<CliImageMode>,

    /// 按名称或 ID 指定服务商（默认取当前启用项）
    #[arg(long)]
    profile: Option<String>,

    /// 不把结果写回剪贴板
    #[arg(long)]
    no_copy: bool,

    /// 不发送桌面通知
    #[arg(long)]
    no_notify: bool,

    /// 输出诊断信息到 stderr
    #[arg(long)]
    verbose: bool,

    /// 指定配置文件路径（默认取用户配置目录）
    #[arg(long)]
    config: Option<PathBuf>,
}

fn resolve_profile<'a>(config: &'a AppConfig, selector: Option<&str>) -> Result<&'a LlmProfile, String> {
    let Some(name) = selector else {
        return Ok(config.get_active_profile());
    };
    let lower = name.to_lowercase();
    if let Some(p) = config
        .profiles
        .iter()
        .find(|p| p.id.to_lowercase() == lower || p.name.to_lowercase() == lower)
    {
        return Ok(p);
    }
    let available = config
        .profiles
        .iter()
        .map(|p| p.name.as_str())
        .collect::<Vec<_>>()
        .join(", ");
    Err(format!("未找到服务商「{name}」。可选：{available}"))
}

enum InputPayload {
    Text(String),
    Image(Vec<u8>),
}

async fn collect_input(args: &Args) -> Result<InputPayload, String> {
    if args.screenshot {
        let png = capture_region_wayland().await.map_err(|e| e.to_string())?;
        return Ok(InputPayload::Image(png));
    }
    if args.image {
        let png = read_clipboard_image_png().await.map_err(|e| e.to_string())?;
        return Ok(InputPayload::Image(png));
    }
    let text = if args.primary {
        read_primary_selection_text().await.map_err(|e| e.to_string())?
    } else if args.clipboard {
        read_clipboard_text().await.map_err(|e| e.to_string())?
    } else if !args.text.is_empty() {
        args.text.join(" ")
    } else if !io::stdin().is_terminal() {
        let mut buf = String::new();
        io::stdin()
            .read_to_string(&mut buf)
            .map_err(|e| format!("读取标准输入失败：{e}"))?;
        buf
    } else {
        return Err("请提供待翻译文本，或指定 --clipboard / --image / --screenshot".to_string());
    };

    let trimmed = text.trim().to_string();
    if trimmed.is_empty() {
        return Err("没有可翻译的文本".to_string());
    }
    Ok(InputPayload::Text(trimmed))
}

#[tokio::main]
async fn main() -> ExitCode {
    let args = Args::parse();

    let payload = match collect_input(&args).await {
        Ok(p) => p,
        Err(msg) => {
            eprintln!("错误：{msg}");
            return ExitCode::from(1);
        }
    };

    let store = ConfigStore::new(args.config.clone());
    let config = store.load();
    let profile = match resolve_profile(&config, args.profile.as_deref()) {
        Ok(p) => p.clone(),
        Err(msg) => {
            eprintln!("错误：{msg}");
            return ExitCode::from(1);
        }
    };

    let translation = &config.translation;
    let source_lang = args.source.as_deref().unwrap_or(&translation.source_lang);
    let target_lang = args.target.as_deref().unwrap_or(&translation.target_lang);
    let extra = effective_extra_prompt(translation);
    let glossary = if translation.glossary.is_empty() {
        None
    } else {
        Some(&translation.glossary)
    };

    let translator = Translator::new(OcrService::new(&translation.tesseract_path, 60.0));

    let res = match payload {
        InputPayload::Image(png) => {
            let mode: ImageMode = args
                .mode
                .clone()
                .map(Into::into)
                .unwrap_or_else(|| translation.image_mode.clone());
            if args.verbose {
                eprintln!("[mode] {:?} ({} bytes)", mode, png.len());
            }
            translator
                .translate_image(
                    &png,
                    &mode,
                    source_lang,
                    target_lang,
                    &profile,
                    &extra,
                    glossary,
                    &translation.ocr_langs,
                )
                .await
        }
        InputPayload::Text(text) => {
            if args.verbose {
                eprintln!("[text] {} chars", text.chars().count());
            }
            translator
                .translate_text_with_options(
                    &text,
                    source_lang,
                    target_lang,
                    &profile,
                    &extra,
                    glossary,
                    translation.auto_dictionary,
                )
                .await
        }
    };

    let result = match res {
        Ok(r) => r,
        Err(e) => {
            eprintln!("错误：{e}");
            return ExitCode::from(1);
        }
    };

    let output = result.text.trim();
    if !output.is_empty() {
        println!("{output}");
    }

    if !args.no_copy {
        match write_clipboard_text(output).await {
            Ok(()) if args.verbose => eprintln!("[copied] 已复制到剪贴板"),
            Err(_) if args.verbose => eprintln!("[copy skipped] 无可用剪贴板写入工具"),
            _ => {}
        }
    }

    if !args.no_notify {
        send_notification(
            "AI 翻译",
            if output.is_empty() { "（空结果）" } else { output },
        )
        .await;
    }

    if args.verbose {
        eprintln!("[model] {}", result.model);
    }

    ExitCode::SUCCESS
}
