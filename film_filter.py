# -*- coding: utf-8 -*-
"""
Local Lightweight Film Grain Filter (本地轻量胶片滤镜算法)
--------------------------------------------------------
专用于突破上游 AI 视频/图像模型（如 Dreamina / Seedance 2.0 / 2.5）对真人面部的风控拦截（Likeness Protection / Real People Restriction）。
在 100% 保持面部五官轮廓、眼神结构、身份特征、表情神态的前提下，
通过轻量级多尺度有机胶片银盐颗粒调制、高光/暗部自适应光强掩膜、微量胶片光晕漫射（Halation Diffusion）
以及柔和 S-Curve 胶片影调映射，彻底消除数码相机传感器原生平滑指纹，使模型将其识别为具质感的电影/胶片艺术画面，
从而顺利放行并高质量生成视频。
"""

import base64
import io
import math
import random
from typing import Optional, Tuple, Union

try:
    import numpy as np
    from PIL import Image, ImageFilter
    HAS_FILTER_DEPS = True
except ImportError:
    HAS_FILTER_DEPS = False


def apply_film_grain_image(
    img: "Image.Image",
    grain_intensity: float = 12.5,
    apply_curve: bool = True,
    warmth_factor: float = 0.018,
    halation_blend: float = 0.08,
) -> "Image.Image":
    """
    对 PIL Image 对象应用轻量有机胶片银盐颗粒与光晕微漫射滤镜。
    
    :param img: 输入 PIL 图像 (RGB/RGBA)
    :param grain_intensity: 胶片颗粒强度（11.0 - 14.0 为破除风控最佳平衡点）
    :param apply_curve: 是否应用微调电影 S-Curve 影调
    :param warmth_factor: 胶片轻微暖调偏置（打破机械数码白平衡）
    :param halation_blend: 微量胶片高光边缘光晕漫射（打破子像素级平滑边缘）
    :return: 滤镜处理后的 PIL Image
    """
    if not HAS_FILTER_DEPS:
        return img

    # 1. 统一转为 RGB
    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "RGBA":
            bg.paste(img, mask=img.split()[3])
        else:
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[3])
        work_img = bg
    elif img.mode != "RGB":
        work_img = img.convert("RGB")
    else:
        work_img = img

    # 2. 胶片微光晕漫射 (Halation Micro-Diffusion)
    # 模拟柯达电影胶片的高光边缘柔光漫射，有效破坏人脸检测模型对数码锐利边缘的置信度，而肉眼观察依然极其清晰
    if halation_blend > 0:
        halo = work_img.filter(ImageFilter.GaussianBlur(radius=1.2))
        work_img = Image.blend(work_img, halo, halation_blend)

    arr = np.array(work_img, dtype=np.float32)
    h, w, _ = arr.shape

    # 3. 亮度计算 (BT.709 经典感官亮度加权)
    lum = (0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]) / 255.0
    grain_mask = np.clip(4.0 * lum * (1.0 - lum), 0.18, 1.0)[:, :, np.newaxis]

    # 4. 单色有机高斯颗粒 (Monochromatic Gaussian Film Grain)
    noise = np.random.normal(0.0, grain_intensity, (h, w, 1)).astype(np.float32)
    arr = arr + noise * grain_mask

    # 5. 胶片影调微对比度 (Film S-Curve & Color Grading)
    if apply_curve:
        norm = np.clip(arr / 255.0, 0.0, 1.0)
        scurve = 3.0 * (norm ** 2) - 2.0 * (norm ** 3)
        norm = norm * 0.72 + scurve * 0.28
        
        if warmth_factor > 0:
            norm[:, :, 0] = np.clip(norm[:, :, 0] * (1.0 + warmth_factor), 0.0, 1.0)
            norm[:, :, 2] = np.clip(norm[:, :, 2] * (1.0 - warmth_factor), 0.0, 1.0)
            
        arr = norm * 255.0

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def process_image_bytes(
    raw_bytes: bytes,
    grain_intensity: float = 12.5,
    apply_curve: bool = True,
    max_dim: int = 1280,
    jpeg_quality: int = 92,
) -> bytes:
    """
    处理原始图片二进制流，施加胶片滤镜并重置编码。
    """
    if not HAS_FILTER_DEPS or not raw_bytes:
        return raw_bytes

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            w, h = img.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

            filtered = apply_film_grain_image(img, grain_intensity=grain_intensity, apply_curve=apply_curve)
            
            buf = io.BytesIO()
            filtered.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
            return buf.getvalue()
    except Exception:
        return raw_bytes


def process_b64_data_url(
    data_url: str,
    grain_intensity: float = 12.5,
    apply_curve: bool = True,
    max_dim: int = 1280,
    max_bytes: int = 700_000,
) -> str:
    """
    专门针对 Base64 Data URL (data:image/...;base64,...) 施加轻量胶片滤镜与体积优化。
    """
    if not HAS_FILTER_DEPS or not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        return data_url

    try:
        _, separator, encoded = data_url.partition(",")
        if not separator:
            return data_url
        raw = base64.b64decode(encoded)
        with Image.open(io.BytesIO(raw)) as img:
            w, h = img.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

            filtered = apply_film_grain_image(img, grain_intensity=grain_intensity, apply_curve=apply_curve)

            buf = io.BytesIO()
            quality = 90
            filtered.save(buf, format="JPEG", quality=quality, optimize=True)
            while buf.tell() > max_bytes and quality > 45:
                quality -= 15
                buf = io.BytesIO()
                filtered.save(buf, format="JPEG", quality=quality, optimize=True)

            out_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{out_b64}"
    except Exception:
        return data_url
