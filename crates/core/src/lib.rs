pub mod config;
pub mod imaging;
pub mod jev_client;
pub mod languages;
pub mod llm_client;
pub mod ocr;
pub mod platform;
pub mod presets;
pub mod prompts;
pub mod providers;
pub mod translator;
pub mod tts;

pub const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
