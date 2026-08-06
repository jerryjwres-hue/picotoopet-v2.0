from picotoopet_core import __version__
from picotoopet_core.versioning import PRODUCT_VERSION


def test_package_exposes_canonical_user_product_version() -> None:
    """运行时包必须从唯一资源暴露当前四段式用户版本。"""

    assert __version__ == PRODUCT_VERSION == "2.3.12.1"
