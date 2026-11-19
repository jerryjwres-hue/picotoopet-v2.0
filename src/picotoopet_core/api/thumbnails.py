"""供执行器和历史素材导入共享的 JPEG 校验。"""

from io import BytesIO

from PIL import Image

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.executor import THUMBNAIL_LIMIT


def validate_thumbnail(jpeg: bytes) -> None:
    if len(jpeg) > THUMBNAIL_LIMIT:
        raise ApiError(
            status_code=413,
            code="VALIDATION_ERROR",
            message="缩略图不能超过 300 KB。",
            retryable=False,
        )
    try:
        with Image.open(BytesIO(jpeg), formats=["JPEG"]) as image:
            if max(image.size) > 8192:
                raise ValueError("JPEG dimensions")
            image.load()
    except (OSError, Image.DecompressionBombError, ValueError) as exc:
        raise ApiError(
            status_code=415,
            code="VALIDATION_ERROR",
            message="缩略图必须是有效的 JPEG 文件。",
            retryable=False,
        ) from exc
