//! Image helpers: MIME sniffing, PNG normalization, vision downscaling, and OCR upscaling.

use std::io::Cursor;

use image::codecs::jpeg::JpegEncoder;
use image::imageops::FilterType;
use image::{ColorType, DynamicImage, ImageFormat};
use thiserror::Error;

pub const VISION_MAX_DIM: u32 = 2000;
pub const VISION_JPEG_QUALITY: u8 = 85;
const PASSTHROUGH_BYTES: usize = 256 * 1024;

#[derive(Debug, Error)]
pub enum ImageError {
    #[error("Invalid image data: {0}")]
    Invalid(String),
}

pub fn sniff_image_mime(data: &[u8]) -> &'static str {
    if data.starts_with(b"\x89PNG\r\n\x1a\n") {
        return "image/png";
    }
    if data.starts_with(&[0xff, 0xd8]) {
        return "image/jpeg";
    }
    if data.starts_with(b"GIF87a") || data.starts_with(b"GIF89a") {
        return "image/gif";
    }
    if data.starts_with(b"BM") {
        return "image/bmp";
    }
    if data.len() >= 12 && &data[0..4] == b"RIFF" && &data[8..12] == b"WEBP" {
        return "image/webp";
    }
    "application/octet-stream"
}

fn has_alpha(color: ColorType) -> bool {
    matches!(
        color,
        ColorType::La8 | ColorType::Rgba8 | ColorType::La16 | ColorType::Rgba16 | ColorType::Rgba32F
    )
}

pub fn normalize_to_png(raw: &[u8]) -> Result<Vec<u8>, ImageError> {
    let img = image::load_from_memory(raw).map_err(|e| ImageError::Invalid(e.to_string()))?;
    let mut out = Cursor::new(Vec::new());
    img.write_to(&mut out, ImageFormat::Png)
        .map_err(|e| ImageError::Invalid(e.to_string()))?;
    Ok(out.into_inner())
}

pub fn downscale_for_vision(png: &[u8], max_dim: u32, jpeg_quality: u8) -> Vec<u8> {
    let Ok(mut img) = image::load_from_memory(png) else {
        return png.to_vec();
    };
    let (w, h) = (img.width(), img.height());
    let longest = w.max(h);
    let oversized = longest > max_dim;

    if !oversized && png.len() <= PASSTHROUGH_BYTES {
        return png.to_vec();
    }

    if oversized {
        let scale = max_dim as f64 / longest as f64;
        let nw = ((w as f64 * scale).round() as u32).max(1);
        let nh = ((h as f64 * scale).round() as u32).max(1);
        img = img.resize_exact(nw, nh, FilterType::Lanczos3);
    }

    let encoded = if has_alpha(img.color()) {
        let mut buf = Cursor::new(Vec::new());
        if img.write_to(&mut buf, ImageFormat::Png).is_err() {
            return png.to_vec();
        }
        buf.into_inner()
    } else {
        let rgb = img.to_rgb8();
        let mut buf = Vec::new();
        let mut enc = JpegEncoder::new_with_quality(&mut buf, jpeg_quality);
        if enc.encode_image(&DynamicImage::ImageRgb8(rgb)).is_err() {
            return png.to_vec();
        }
        buf
    };

    if oversized || encoded.len() < png.len() {
        encoded
    } else {
        png.to_vec()
    }
}

pub fn prepare_for_ocr(png: &[u8], upscale_below: u32, max_dim: u32) -> Vec<u8> {
    let Ok(img) = image::load_from_memory(png) else {
        return png.to_vec();
    };
    let (w, h) = (img.width(), img.height());
    let longest = w.max(h);
    if longest >= upscale_below || longest == 0 {
        return png.to_vec();
    }
    let scale = (2.0_f64).min(max_dim as f64 / longest as f64);
    if scale <= 1.0 {
        return png.to_vec();
    }
    let nw = ((w as f64 * scale).round() as u32).max(1);
    let nh = ((h as f64 * scale).round() as u32).max(1);
    let resized = img.resize_exact(nw, nh, FilterType::Lanczos3);
    let rgb = DynamicImage::ImageRgb8(resized.to_rgb8());
    let mut out = Cursor::new(Vec::new());
    if rgb.write_to(&mut out, ImageFormat::Png).is_err() {
        return png.to_vec();
    }
    out.into_inner()
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{ImageBuffer, Rgb};

    fn make_png(w: u32, h: u32) -> Vec<u8> {
        let img: ImageBuffer<Rgb<u8>, Vec<u8>> = ImageBuffer::from_fn(w, h, |x, y| {
            Rgb([(x % 256) as u8, (y % 256) as u8, 128])
        });
        let mut out = Cursor::new(Vec::new());
        DynamicImage::ImageRgb8(img)
            .write_to(&mut out, ImageFormat::Png)
            .unwrap();
        out.into_inner()
    }

    #[test]
    fn sniff_detects_png_and_jpeg() {
        let png = make_png(8, 8);
        assert_eq!(sniff_image_mime(&png), "image/png");
        assert_eq!(sniff_image_mime(&[0xff, 0xd8, 0xff]), "image/jpeg");
    }

    #[test]
    fn vision_downscales_oversized_image() {
        let big = make_png(2400, 1200);
        let out = downscale_for_vision(&big, VISION_MAX_DIM, VISION_JPEG_QUALITY);
        assert_eq!(sniff_image_mime(&out), "image/jpeg");
        let decoded = image::load_from_memory(&out).unwrap();
        assert_eq!(decoded.width(), 2000);
        assert_eq!(decoded.height(), 1000);
    }

    #[test]
    fn ocr_upscales_small_image() {
        let small = make_png(200, 100);
        let out = prepare_for_ocr(&small, 1000, 2400);
        let decoded = image::load_from_memory(&out).unwrap();
        assert_eq!(decoded.width(), 400);
        assert_eq!(decoded.height(), 200);
    }
}
