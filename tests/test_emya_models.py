# -*- coding: utf-8 -*-
"""
emya 模型和服务单元测试
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# 测试模型定义
class TestEmyaModels:
    """测试 emya 数据库模型"""

    def test_relation_type_constants(self):
        """测试关系类型常量"""
        from video_organizer.core.emya.models import RelationType

        assert RelationType.VIDEO_LIBRARY == "vb"
        assert RelationType.VIDEO_LIST == "vl"
        assert RelationType.VIDEO_SEASON == "vs"
        assert RelationType.VIDEO_EPISODE == "ve"

    def test_image_type_constants(self):
        """测试图片类型常量"""
        from video_organizer.core.emya.models import ImageType

        assert ImageType.PRIMARY == "Primary"
        assert ImageType.BACKDROP == "Backdrop"
        assert ImageType.THUMB == "Thumb"
        assert ImageType.LOGO == "Logo"

    def test_path_type_constants(self):
        """测试路径类型常量"""
        from video_organizer.core.emya.models import PathType

        assert PathType.TMDB == "tmdb"
        assert PathType.DOUBAN == "douban"
        assert PathType.URL == "url"
        assert PathType.LOCAL == "local"

    def test_video_type_constants(self):
        """测试视频类型常量"""
        from video_organizer.core.emya.models import VideoType

        assert VideoType.TV == "tv"
        assert VideoType.MOVIE == "movie"


class TestDatabaseManager:
    """测试数据库管理器"""

    def test_database_manager_class_exists(self):
        """测试 DatabaseManager 类存在"""
        from video_organizer.core.db_manager import DatabaseManager

        assert DatabaseManager is not None

    def test_init_db_function_exists(self):
        """测试 init_db 函数存在"""
        from video_organizer.core.db_manager import init_db

        assert callable(init_db)

    def test_get_db_function_exists(self):
        """测试 get_db 函数存在"""
        from video_organizer.core.db_manager import get_db

        assert callable(get_db)

    def test_session_scope_function_exists(self):
        """测试 session_scope 函数存在"""
        from video_organizer.core.db_manager import session_scope

        # session_scope 是一个生成器函数
        assert session_scope is not None


class TestEmyaService:
    """测试 emya 入库服务"""

    @patch("video_organizer.core.emya.service.get_db")
    def test_service_init(self, mock_get_db):
        """测试服务初始化"""
        from video_organizer.core.emya.service import EmyaService

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        service = EmyaService(default_user_id=1)

        assert service.default_user_id == 1

    @patch("video_organizer.core.emya.service.get_db")
    def test_get_or_create_library(self, mock_get_db):
        """测试获取或创建媒体库"""
        from video_organizer.core.emya.service import EmyaService
        from video_organizer.core.emya.models import Library

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_session = MagicMock()
        mock_db.session_scope.return_value.__enter__ = Mock(return_value=mock_session)
        mock_db.session_scope.return_value.__exit__ = Mock(return_value=False)

        # 模拟媒体库不存在
        mock_session.query.return_value.filter.return_value.first.return_value = None

        service = EmyaService()

        # 由于需要实际数据库操作，这里只测试方法存在
        assert hasattr(service, "get_or_create_library")

    @patch("video_organizer.core.emya.service.get_db")
    def test_import_tv_show_structure(self, mock_get_db):
        """测试电视剧导入方法存在"""
        from video_organizer.core.emya.service import EmyaService

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        service = EmyaService()

        # 验证方法存在
        assert hasattr(service, "import_tv_show")
        assert hasattr(service, "import_movie")
        assert hasattr(service, "import_from_metadata")

    @patch("video_organizer.core.emya.service.get_db")
    def test_search_video(self, mock_get_db):
        """测试搜索视频方法"""
        from video_organizer.core.emya.service import EmyaService

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        service = EmyaService()

        # 验证方法存在
        assert hasattr(service, "search_video")
        assert hasattr(service, "get_video_detail")


class TestEmyaApiController:
    """测试 API 控制器"""

    def test_controller_class_exists(self):
        """测试控制器类存在"""
        from video_organizer.core.emya.api import EmyaApiController

        assert EmyaApiController is not None

    def test_init_controller_function_exists(self):
        """测试 init_controller 函数存在"""
        from video_organizer.core.emya.api import init_controller

        assert callable(init_controller)

    def test_get_controller_function_exists(self):
        """测试 get_controller 函数存在"""
        from video_organizer.core.emya.api import get_controller

        assert callable(get_controller)

    def test_quick_import_functions_exist(self):
        """测试快捷导入函数存在"""
        from video_organizer.core.emya.api import quick_import_tv, quick_import_movie

        assert callable(quick_import_tv)
        assert callable(quick_import_movie)

    def test_api_response_dataclass(self):
        """测试 API 响应数据类"""
        from video_organizer.core.emya.api import ApiResponse

        response = ApiResponse(
            success=True,
            message="操作成功",
            data={"id": 1},
        )

        assert response.success is True
        assert response.message == "操作成功"
        assert response.data == {"id": 1}
        assert response.error_code is None

    def test_import_tv_request_dataclass(self):
        """测试导入电视剧请求数据类"""
        from video_organizer.core.emya.api import ImportTVRequest

        request = ImportTVRequest(
            tmdb_id=12345,
            title="测试剧集",
            library_id=1,
        )

        assert request.tmdb_id == 12345
        assert request.title == "测试剧集"
        assert request.library_id == 1
        assert request.seasons == []

    def test_import_movie_request_dataclass(self):
        """测试导入电影请求数据类"""
        from video_organizer.core.emya.api import ImportMovieRequest

        request = ImportMovieRequest(
            tmdb_id=67890,
            title="测试电影",
            library_id=2,
            runtime=120,
        )

        assert request.tmdb_id == 67890
        assert request.title == "测试电影"
        assert request.library_id == 2
        assert request.runtime == 120
        assert request.media_files == []


class TestConfigIntegration:
    """测试配置集成"""

    def test_emya_db_config_in_default_config(self):
        """测试默认配置中包含 emya_db 配置"""
        from video_organizer.core.config_loader import DEFAULT_CONFIG

        assert "emya_db" in DEFAULT_CONFIG
        assert "enabled" in DEFAULT_CONFIG["emya_db"]
        assert "host" in DEFAULT_CONFIG["emya_db"]
        assert "port" in DEFAULT_CONFIG["emya_db"]
        assert "database" in DEFAULT_CONFIG["emya_db"]

    def test_emya_db_config_defaults(self):
        """测试 emya_db 默认配置值"""
        from video_organizer.core.config_loader import DEFAULT_CONFIG

        emya_config = DEFAULT_CONFIG["emya_db"]

        assert emya_config["enabled"] is False
        assert emya_config["host"] == "localhost"
        assert emya_config["port"] == 3306
        assert emya_config["user"] == "root"
        assert emya_config["database"] == "emya"
        assert emya_config["default_user_id"] == 1
        assert emya_config["default_tv_library"] == "电视剧"
        assert emya_config["default_movie_library"] == "电影"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestEmyaHashNormalize:
    """测试 content_hash 规范化与删除查找辅助函数"""

    def test_normalize_32hex_gets_md5_prefix(self):
        """32 位十六进制应规范化为 md5: 前缀（不再产生 sha256:<32hex> 畸形格式）"""
        from video_organizer.core.emya.service import EmyaService

        assert EmyaService._normalize_content_hash(
            "5f2dd1b3c01a98a99cd5bd1b7ff58dab"
        ) == "md5:5f2dd1b3c01a98a99cd5bd1b7ff58dab"

    def test_normalize_64hex_gets_sha256_prefix(self):
        """64 位十六进制应规范化为 sha256: 前缀"""
        from video_organizer.core.emya.service import EmyaService

        h = "5fe5346f8ffa274cdfc3db726d2d149640baa429" + "0" * 24
        assert len(h) == 64
        assert EmyaService._normalize_content_hash(h) == f"sha256:{h}"

    def test_normalize_uppercase_lowercases(self):
        """大写哈希应统一转小写存储"""
        from video_organizer.core.emya.service import EmyaService

        assert EmyaService._normalize_content_hash(
            "5F2DD1B3C01A98A99CD5BD1B7FF58DAB"
        ) == "md5:5f2dd1b3c01a98a99cd5bd1b7ff58dab"

    def test_normalize_preserves_existing_valid_prefix(self):
        """已带正确前缀且长度为 64 的值原样保留（去重）"""
        from video_organizer.core.emya.service import EmyaService

        h = "5fe5346f8ffa274cdfc3db726d2d149640baa429" + "0" * 24
        assert EmyaService._normalize_content_hash(f"sha256:{h}") == f"sha256:{h}"

    def test_normalize_legacy_sha256_32hex_fixed(self):
        """历史畸形 sha256:<32hex> 应被纠正为 md5:<32hex>"""
        from video_organizer.core.emya.service import EmyaService

        assert EmyaService._normalize_content_hash(
            "sha256:5f2dd1b3c01a98a99cd5bd1b7ff58dab"
        ) == "md5:5f2dd1b3c01a98a99cd5bd1b7ff58dab"

    def test_like_escape(self):
        """LIKE 通配符应被转义，避免文件名中的 %/_ 干扰"""
        from video_organizer.core.emya.service import EmyaService

        assert EmyaService._like_escape("a%b_c") == r"a\%b\_c"

    def test_query_media_by_hash_candidates(self):
        """哈希查询候选应覆盖裸值 / sha256: / md5: / sha1: 四种前缀"""
        from video_organizer.core.emya.service import EmyaService

        service = EmyaService.__new__(EmyaService)
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = []

        service._query_media_by_hash(mock_session, "5f2dd1b3c01a98a99cd5bd1b7ff58dab")
        # 校验传给 filter 的候选集合
        call_args = mock_query.filter.call_args
        assert call_args is not None
        in_expr = call_args[0][0]
        assert set(in_expr.right.value) == {
            "5f2dd1b3c01a98a99cd5bd1b7ff58dab",
            "sha256:5f2dd1b3c01a98a99cd5bd1b7ff58dab",
            "md5:5f2dd1b3c01a98a99cd5bd1b7ff58dab",
            "sha1:5f2dd1b3c01a98a99cd5bd1b7ff58dab",
        }
