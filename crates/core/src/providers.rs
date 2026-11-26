//! Well-known OpenAI-compatible provider templates for onboarding.

use serde::Serialize;

#[derive(Debug, Clone, Copy, Serialize)]
pub struct ProviderTemplate {
    pub id: &'static str,
    pub name: &'static str,
    pub base_url: &'static str,
    pub text_model: &'static str,
    pub vision_model: &'static str,
    pub api_protocol: &'static str,
    pub key_required: bool,
    pub hint: &'static str,
}

pub const PROVIDER_TEMPLATES: &[ProviderTemplate] = &[
    ProviderTemplate {
        id: "openai",
        name: "OpenAI",
        base_url: "https://api.openai.com/v1",
        text_model: "gpt-4o-mini",
        vision_model: "gpt-4o-mini",
        api_protocol: "chat_completions",
        key_required: true,
        hint: "platform.openai.com 申请 API Key，gpt-4o-mini 同时支持文本与图片。",
    },
    ProviderTemplate {
        id: "deepseek",
        name: "DeepSeek（深度求索）",
        base_url: "https://api.deepseek.com/v1",
        text_model: "deepseek-chat",
        vision_model: "",
        api_protocol: "chat_completions",
        key_required: true,
        hint: "platform.deepseek.com 申请 Key。官方接口暂无视觉模型，图片翻译请用 OCR 模式。",
    },
    ProviderTemplate {
        id: "siliconflow",
        name: "SiliconFlow（硅基流动）",
        base_url: "https://api.siliconflow.cn/v1",
        text_model: "deepseek-ai/DeepSeek-V3",
        vision_model: "Qwen/Qwen2.5-VL-32B-Instruct",
        api_protocol: "chat_completions",
        key_required: true,
        hint: "cloud.siliconflow.cn 申请 Key，国内直连，托管大量开源模型。",
    },
    ProviderTemplate {
        id: "moonshot",
        name: "Moonshot（Kimi）",
        base_url: "https://api.moonshot.cn/v1",
        text_model: "moonshot-v1-8k",
        vision_model: "moonshot-v1-8k-vision-preview",
        api_protocol: "chat_completions",
        key_required: true,
        hint: "platform.moonshot.cn 申请 Key。",
    },
    ProviderTemplate {
        id: "zhipu",
        name: "智谱 GLM",
        base_url: "https://open.bigmodel.cn/api/paas/v4",
        text_model: "glm-4-flash",
        vision_model: "glm-4v-flash",
        api_protocol: "chat_completions",
        key_required: true,
        hint: "open.bigmodel.cn 申请 Key，glm-4-flash / glm-4v-flash 免费。",
    },
    ProviderTemplate {
        id: "dashscope",
        name: "阿里云百炼（Qwen）",
        base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        text_model: "qwen-plus",
        vision_model: "qwen-vl-plus",
        api_protocol: "chat_completions",
        key_required: true,
        hint: "阿里云百炼控制台申请 Key，此为 OpenAI 兼容模式地址。",
    },
    ProviderTemplate {
        id: "openrouter",
        name: "OpenRouter（聚合中转）",
        base_url: "https://openrouter.ai/api/v1",
        text_model: "openai/gpt-4o-mini",
        vision_model: "openai/gpt-4o-mini",
        api_protocol: "chat_completions",
        key_required: true,
        hint: "openrouter.ai 一个 Key 用遍各家模型，模型名带厂商前缀。",
    },
    ProviderTemplate {
        id: "gemini",
        name: "Google Gemini（OpenAI 兼容）",
        base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
        text_model: "gemini-2.0-flash",
        vision_model: "gemini-2.0-flash",
        api_protocol: "chat_completions",
        key_required: true,
        hint: "aistudio.google.com 申请 Key，Gemini 原生多模态。",
    },
    ProviderTemplate {
        id: "ollama",
        name: "Ollama（本地）",
        base_url: "http://127.0.0.1:11434/v1",
        text_model: "",
        vision_model: "",
        api_protocol: "chat_completions",
        key_required: false,
        hint: "无需 API Key。先 ollama serve 启动服务，ollama pull 拉模型；视觉模型如 llava。",
    },
    ProviderTemplate {
        id: "lmstudio",
        name: "LM Studio（本地）",
        base_url: "http://127.0.0.1:1234/v1",
        text_model: "",
        vision_model: "",
        api_protocol: "chat_completions",
        key_required: false,
        hint: "无需 API Key。在 LM Studio 中启动本地服务器后即可拉取模型列表。",
    },
];

pub fn get_template(id: &str) -> Option<&'static ProviderTemplate> {
    PROVIDER_TEMPLATES.iter().find(|t| t.id == id)
}
