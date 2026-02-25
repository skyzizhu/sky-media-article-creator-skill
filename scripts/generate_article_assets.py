#!/usr/bin/env python
"""
Generate cover and inline illustration images for an article using an external image API.

Expected workflow:
- The article text contains HTML comment markers that describe desired images, e.g.:

  <!-- IMAGE: cover | prompt=作者因为自己时间管理混乱而决定做一款时间管理 APP 的场景插画 | aspect=16:9 -->
  <!-- IMAGE: inline | name=时间前后对比 | prompt=展示使用 APP 前后日程混乱与有序对比的插画 | aspect=16:9 -->

- This script:
  - Reads the article file
  - Parses IMAGE markers
  - Calls an external image API for each marker
  - Saves all images into the output directory
  - Replaces inline markers with plain-text placeholders and writes an updated article file

You MUST customize the IMAGE_API_URL / headers / payload format to match your own API.
"""

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover - environment specific
    requests = None


# Default to DashScope Qwen Image API, but allow override via IMAGE_API_URL.
IMAGE_API_URL = os.environ.get(
    "IMAGE_API_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
)
# 优先使用 IMAGE_API_KEY，如未设置则回退到 ALI_DASHSCOPE_API_KEY
IMAGE_API_KEY = os.environ.get("IMAGE_API_KEY") or os.environ.get(
    "ALI_DASHSCOPE_API_KEY", "sk-f27f0dd277af4823a90bca92d2c6fc32"
)


@dataclass
class ImageMarker:
    kind: str  # "cover" or "inline"
    prompt: str
    aspect: Optional[str]
    name: Optional[str]
    index: int  # appearance order for naming
    span: Tuple[int, int]  # (start_index, end_index) in the original text


MARKER_PATTERN = re.compile(
    r"<!--\s*IMAGE:\s*(?P<body>.+?)\s*-->", re.IGNORECASE | re.DOTALL
)


def parse_marker_body(body: str, index: int) -> Optional[ImageMarker]:
    """
    Parse the body of an IMAGE marker, which is expected to look like:
      "cover | prompt=... | aspect=16:9"
      "inline | name=xxx | prompt=... | aspect=4:3"
    """
    parts = [p.strip() for p in body.split("|") if p.strip()]
    if not parts:
        return None

    kind = parts[0].lower()
    if kind not in {"cover", "inline"}:
        return None

    prompt = None
    aspect = None
    name = None

    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        # strip optional surrounding quotes
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        if key == "prompt":
            prompt = value
        elif key == "aspect":
            aspect = value
        elif key == "name":
            name = value

    if not prompt:
        return None

    return ImageMarker(
        kind=kind,
        prompt=prompt,
        aspect=aspect,
        name=name,
        index=index,
        span=(0, 0),  # filled later
    )


def find_image_markers(text: str) -> List[ImageMarker]:
    markers: List[ImageMarker] = []
    for idx, match in enumerate(MARKER_PATTERN.finditer(text), start=1):
        body = match.group("body")
        marker = parse_marker_body(body, idx)
        if marker is None:
            continue
        marker.span = (match.start(), match.end())
        markers.append(marker)
    return markers


def _aspect_to_size(aspect: Optional[str]) -> Optional[str]:
    """
    Convert an aspect string to DashScope size, if possible.

    - If aspect looks like "W*H", use it directly.
    - If aspect is a ratio like "16:9", map to一个常用分辨率。
    - If None or未知，则返回 None 让 API 使用默认。
    """
    if not aspect:
        return None

    aspect = aspect.strip()
    # Already looks like "width*height"
    if "*" in aspect:
        return aspect

    ratio_map = {
        "16:9": "1696*960",
        "3:2": "1472*976",
        "4:3": "1472*1104",
        "1:1": "1024*1024",
        "9:16": "960*1696",
    }
    return ratio_map.get(aspect, None)


def _simplify_cover_text(text: str) -> str:
    """
    Simplify long cover text into short keyword-style copy.
    Example:
    "我用vibe coding做了一款工具App，也重新理解了AI产品"
    -> "vibe coding + 工具APP"
    """
    raw = text.strip()
    if not raw:
        return raw

    lowered = raw.lower()
    has_vibe = "vibe coding" in lowered or ("vibe" in lowered and "coding" in lowered)
    has_tool_app = ("工具" in raw) and ("app" in lowered or "应用" in raw)
    has_ai = "ai" in lowered or "人工智能" in raw
    has_product = "产品" in raw

    parts: List[str] = []
    if has_vibe:
        parts.append("vibe coding")
    if has_tool_app:
        parts.append("工具APP")
    elif "工具" in raw:
        parts.append("工具软件")
    if has_ai and has_product and "AI产品" not in parts:
        parts.append("AI产品")
    elif has_ai and "AI" not in parts:
        parts.append("AI")

    if not parts:
        # Fallback: keep a short, readable chunk.
        compact = re.sub(r"[，。、“”\"'：:；;！!？?\s]+", "", raw)
        return compact[:8]

    return " + ".join(parts[:2])


def _normalize_cover_text_in_prompt(prompt: str) -> str:
    """
    If the prompt contains a long quoted cover text, replace it with a simplified version.
    """
    candidates = re.findall(r"[“\"]([^”\"]{8,80})[”\"]", prompt)
    if not candidates:
        return prompt

    target = max(candidates, key=len)
    # If the quoted text is already short enough, keep it.
    if len(target) <= 14:
        return prompt

    simplified = _simplify_cover_text(target)
    return prompt.replace(target, simplified, 1)


def _enhance_prompt(prompt: str, kind: str) -> str:
    """
    Add stable quality constraints so generated images stay aligned with article core content.
    """
    base = prompt.strip()
    if kind == "cover":
        base = _normalize_cover_text_in_prompt(base)
        suffix = (
            "。封面必须围绕文章核心内容进行视觉表达，画面中需有清晰、可读的大号中文主题文字；"
            "封面显示文字不要照搬文章完整标题，应压缩为2-8字或2-4个关键词短语（可用“关键词A + 关键词B”形式）；"
            "除主题文字外，加入2-4个与核心内容强相关的图形或物体元素（如文档、齿轮、波形、图表、时间轴、二维码、设备界面等）；"
            "色调浓郁有张力，使用中高饱和与清晰对比，避免灰暗、发闷、低饱和、雾蒙蒙的画面；"
            "构图简洁，信息层次清晰，避免无关装饰。"
        )
    else:
        suffix = (
            "。插图需紧扣对应段落的核心信息，只呈现与该段主题直接相关的元素；"
            "减少无关背景和装饰，优先表达关键动作、关键对比或关键结果；"
            "整体风格保持色彩浓郁、对比明确、视觉有活力，避免灰暗低饱和风格。"
        )
    return f"{base}{suffix}"


def call_image_api(
    prompt: str,
    aspect: Optional[str],
    forbid_people: bool = False,
    max_retries: int = 2,
    retry_delay_sec: float = 1.5,
) -> bytes:
    """
    Call DashScope Qwen image API and return raw image bytes.

    If forbid_people=True, the negative_prompt is set to strongly discourage
    any people / faces in the generated image (useful for cover images).
    """
    if requests is None:
        raise RuntimeError("The 'requests' library is required but not installed.")

    if not IMAGE_API_URL:
        raise RuntimeError(
            "IMAGE_API_URL is not configured. Set it as an environment variable."
        )

    headers = {"Content-Type": "application/json"}
    if IMAGE_API_KEY:
        headers["Authorization"] = f"Bearer {IMAGE_API_KEY}"

    size = _aspect_to_size(aspect)

    negative_prompt = ""
    if forbid_people:
        # Try to cover common Chinese/English tokens for people/faces
        negative_prompt = "人物, 人脸, 人类, 人像, face, faces, person, people, human, portrait"

    payload = {
        "model": "qwen-image-max",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": prompt,
                        }
                    ],
                }
            ]
        },
        "parameters": {
            # 这些参数可按需调整或暴露为可配置项
            "negative_prompt": negative_prompt,
            "prompt_extend": True,
            "watermark": False,
        },
    }
    if size:
        payload["parameters"]["size"] = size

    attempt = 0
    last_err: Optional[Exception] = None

    while attempt <= max_retries:
        try:
            resp = requests.post(IMAGE_API_URL, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as err:
            last_err = err
            if attempt >= max_retries:
                raise RuntimeError(
                    f"Image API request failed after {max_retries + 1} attempts: {err}"
                ) from err
            time.sleep(retry_delay_sec * (attempt + 1))
            attempt += 1
    else:
        raise RuntimeError(f"Image API request failed: {last_err}")

    # 兼容 DashScope 不同返回结构：
    # 1) 老格式: {"output": {"results": [{"url": "..."}]}}
    # 2) 新格式: {"output": {"choices": [{"message": {"content": [{"image": "..."}]}}]}}
    url: Optional[str] = None

    output = data.get("output") or {}

    # 新格式优先
    try:
        choices = output.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            message = first_choice.get("message") or {}
            content_list = message.get("content") or []
            if isinstance(content_list, list) and content_list:
                first_content = content_list[0]
                url = (
                    first_content.get("image")
                    or first_content.get("url")
                    or first_content.get("image_url")
                )
    except Exception:
        url = None

    # 回退到老格式
    if not url:
        try:
            results = output.get("results")
            if isinstance(results, list) and results:
                first = results[0]
                url = (
                    first.get("url")
                    or first.get("image_url")
                    or first.get("image")
                )
        except Exception:
            url = None

    if not url:
        raise RuntimeError(f"No image URL found in API response: {data!r}")

    # 下载图片二进制
    img_resp = requests.get(url, timeout=120)
    img_resp.raise_for_status()
    return img_resp.content


def process_article(
    article_text: str,
    output_dir: Path,
    default_cover_aspect: Optional[str] = None,
) -> Tuple[str, List[Path]]:
    """
    Generate images for all markers and return updated article text + list of image paths.
    """
    markers = find_image_markers(article_text)
    if not markers:
        return article_text, []

    output_dir.mkdir(parents=True, exist_ok=True)

    cover_generated = False
    inline_counter = 0
    image_paths: List[Path] = []

    # We'll reconstruct the article text while replacing inline markers.
    pieces = []
    last_idx = 0

    for marker in markers:
        start, end = marker.span
        # Append text before this marker
        pieces.append(article_text[last_idx:start])

        # Decide file name
        if marker.kind == "cover":
            if cover_generated:
                # Ignore additional cover markers in text
                replacement = ""
                pieces.append(replacement)
                last_idx = end
                continue
            filename = "cover.png"
            cover_generated = True
        else:  # inline
            inline_counter += 1
            filename = f"inline_{inline_counter}.png"

        aspect = marker.aspect or (default_cover_aspect if marker.kind == "cover" else None)
        # 封面图默认禁止出现人物/人脸；插图是否包含人物由 prompt 自行控制
        effective_prompt = _enhance_prompt(marker.prompt, marker.kind)
        raw = call_image_api(
            effective_prompt, aspect, forbid_people=(marker.kind == "cover")
        )

        img_path = output_dir / filename
        with img_path.open("wb") as f:
            f.write(raw)
        image_paths.append(img_path)

        # For cover: usually not嵌入正文，直接移除标记
        if marker.kind == "cover":
            replacement = ""
        else:
            alt = marker.name or f"插图{inline_counter}"
            # 在纯文本文章中，用结构化标记提示插图位置，供用户在自媒体平台手动插入图片
            # 说明：
            # - 名称=来自 IMAGE 标记的 name 字段（或默认“插图X”）
            # - 文件=对应生成的图片文件名（例如 inline_1.png）
            replacement = f"【插图：名称={alt}；文件={filename}】"

        pieces.append(replacement)
        last_idx = end

    # Append remaining text
    pieces.append(article_text[last_idx:])
    new_text = "".join(pieces)
    return new_text, image_paths


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate cover and inline images for an article using an image API."
    )
    parser.add_argument(
        "--article-file",
        required=True,
        help="Path to the input article file (Markdown or plain text).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write the updated article and images into.",
    )
    parser.add_argument(
        "--cover-aspect",
        default=None,
        help="Default aspect ratio for the cover image, e.g. '16:9' or '3:2'. "
        "Can be overridden per marker via aspect=... in the comment.",
    )
    parser.add_argument(
        "--updated-article-name",
        default="article_with_images.txt",
        help="Filename for the updated article (plain text) inside output-dir.",
    )

    args = parser.parse_args(argv)

    article_path = Path(args.article_file)
    if not article_path.is_file():
        raise SystemExit(f"Article file not found: {article_path}")

    output_dir = Path(args.output_dir)

    article_text = article_path.read_text(encoding="utf-8")
    updated_text, image_paths = process_article(
        article_text, output_dir, default_cover_aspect=args.cover_aspect
    )

    updated_article_path = output_dir / args.updated_article_name
    updated_article_path.write_text(updated_text, encoding="utf-8")

    # Optionally also copy the original article into the same folder for reference.
    original_copy_path = output_dir / article_path.name
    if original_copy_path.resolve() != article_path.resolve():
        original_copy_path.write_text(article_text, encoding="utf-8")

    print(f"Updated article written to: {updated_article_path}")
    if image_paths:
        print("Generated images:")
        for p in image_paths:
            print(f"  - {p}")
    else:
        print("No IMAGE markers found; no images generated.")

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
