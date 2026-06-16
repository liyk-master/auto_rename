import asyncio
import json
import logging
import re
import threading
from typing import Any, Dict, Optional

import websockets

logger = logging.getLogger(__name__)

VIDEO_EXT = ('.mp4', '.mkv', '.avi', '.rmvb', '.mov', '.wmv', '.flv', '.ts', '.m2ts', '.webm')


class MediaTrackerClient:
    def __init__(
        self,
        config: Dict[str, Any],
        renamer=None,
        yun139_uploader=None,
    ):
        self.enabled = config.get("enabled", False)
        host = config.get("host", "localhost")
        port = int(config.get("port", 8082))
        token = config.get("token", "")
        self.ws_url = f"ws://{host}:{port}/ws?token={token}"
        self.reconnect_delay = int(config.get("reconnect_delay", 5))
        self.app_mode = config.get("app_mode", True)

        self.renamer = renamer
        self.yun139_uploader = yun139_uploader

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        if not self.enabled:
            logger.info("Media Tracker \u5ba2\u6237\u7aef\u672a\u542f\u7528")
            return
        if not self.renamer:
            logger.warning("Media Tracker \u7f3a\u5c11 renamer\uff0c\u65e0\u6cd5\u542f\u52a8")
            return
        if not self.yun139_uploader:
            logger.warning("Media Tracker \u7f3a\u5c11 yun139_uploader\uff0c\u65e0\u6cd5\u542f\u52a8")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="media-tracker-ws")
        self._thread.start()
        logger.info("Media Tracker \u5ba2\u6237\u7aef\u5df2\u542f\u52a8: %s", self.ws_url)

    def stop(self):
        self._stop_event.set()
        logger.info("Media Tracker \u5ba2\u6237\u7aef\u5df2\u505c\u6b62")

    def _run_loop(self):
        asyncio.run(self._ws_loop())

    async def _ws_loop(self):
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(self.ws_url) as ws:
                    logger.info("\u5df2\u8fde\u63a5\u5230 Media Tracker WebSocket")
                    async for message in ws:
                        if self._stop_event.is_set():
                            break
                        try:
                            data = json.loads(message)
                            await self._handle_message(data)
                        except json.JSONDecodeError:
                            logger.warning("WS \u6d88\u606f\u89e3\u6790\u5931\u8d25: %s", message[:200])
                        except Exception as e:
                            logger.error("WS \u6d88\u606f\u5904\u7406\u5931\u8d25: %s", e, exc_info=True)
            except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
                if not self._stop_event.is_set():
                    logger.warning(
                        "WS \u8fde\u63a5\u65ad\u5f00 (%s), %ss \u540e\u91cd\u8fde...",
                        e, self.reconnect_delay,
                    )
                    await asyncio.sleep(self.reconnect_delay)
            except Exception as e:
                logger.error("WS \u8fde\u63a5\u5f02\u5e38: %s", e, exc_info=True)
                await asyncio.sleep(self.reconnect_delay)

    async def _handle_message(self, data: Dict):
        msg_type = data.get("type")
        payload = data.get("payload", data)
        if msg_type == "new_media":
            self._handle_new_media(payload)

    def _handle_new_media(self, payload: Dict):
        file_name = payload.get("file_name", "")
        sha256 = payload.get("sha256", "")
        file_size = payload.get("file_size", 0)
        tmdb_id = payload.get("tmdb_id")
        media_type = payload.get("media_type")
        title = payload.get("title", file_name)

        if not file_name or not sha256 or not file_size:
            logger.warning("new_media \u6570\u636e\u4e0d\u5b8c\u6574: %s", payload)
            return

        logger.info("\u5904\u7406 new_media: %s (%s bytes)", file_name, file_size)

        try:
            # \u4f18\u5316\u8def\u5f84\uff1a\u5982\u679c\u6709 tmdb_id\uff0c\u8df3\u8fc7 TMDB \u641c\u7d22\u6b65\u9aa4
            if tmdb_id and media_type:
                logger.info("\u4f7f\u7528\u5916\u90e8 tmdb_id=%s \u8df3\u8fc7 TMDB \u641c\u7d22\u6b65\u9aa4", tmdb_id)

                # 1. \u4ece title \u4e2d\u63d0\u53d6\u5b63\u96c6\u4fe1\u606f\uff08\u7b80\u5355\u6b63\u5219\uff09
                season = None
                episode = None
                season_episode_match = re.search(r'S(\d+)E(\d+)', title, re.IGNORECASE)
                if season_episode_match:
                    season = int(season_episode_match.group(1))
                    episode = int(season_episode_match.group(2))
                    logger.info("\u4ece title \u63d0\u53d6\u5b63\u96c6: S%02dE%02d", season, episode)

                # 2. \u6784\u9020\u57fa\u7840 metadata\uff0c\u5305\u542b\u5916\u90e8\u63d0\u4f9b\u7684 tmdb_id
                metadata = {
                    "tmdb_id": tmdb_id,
                    "media_type": media_type,
                    "season": season,
                    "episode": episode,
                    "original_filename": file_name,
                }

                # 3. \u76f4\u63a5\u7528 tmdb_id \u8c03\u7528 TMDB API \u83b7\u53d6\u8be6\u7ec6\u4fe1\u606f
                #    _enrich_with_tmdb \u5185\u90e8\u5df2\u652f\u6301\uff1a\u5f53 metadata["tmdb_id"] \u5b58\u5728\u65f6\uff0c
                #    \u8df3\u8fc7\u641c\u7d22\uff0c\u76f4\u63a5\u8c03\u7528 get_tv_details() \u6216 get_movie_details()
                metadata = self.renamer._enrich_with_tmdb(metadata)

                if not metadata or not metadata.get("tmdb_id"):
                    # TMDB \u67e5\u8be2\u5931\u8d25\uff08tmdb_id \u65e0\u6548\u6216\u7f51\u7edc\u9519\u8bef\uff09\uff0c\u56de\u9000\u5230\u5b8c\u6574\u6d41\u7a0b
                    logger.warning("\u4f7f\u7528 tmdb_id \u67e5\u8be2\u5931\u8d25\uff0c\u56de\u9000\u5230\u6587\u4ef6\u540d\u89e3\u6790")
                    metadata = self.renamer.extract_metadata(
                        file_name, media_type_hint=media_type
                    )
            else:
                # \u539f\u6709\u6d41\u7a0b\uff1a\u5b8c\u6574\u7684\u6587\u4ef6\u540d\u89e3\u6790 + TMDB \u641c\u7d22
                logger.info("\u672a\u63d0\u4f9b tmdb_id\uff0c\u4f7f\u7528\u6807\u51c6\u6d41\u7a0b")
                metadata = self.renamer.extract_metadata(
                    file_name, media_type_hint=media_type
                )

            if not metadata:
                logger.warning("\u65e0\u6cd5\u63d0\u53d6\u5143\u6570\u636e: %s", file_name)
                return

            # \u751f\u6210\u6807\u51c6\u5316\u7684\u8def\u5f84\u7ed3\u6784
            new_path = self.renamer.generate_new_path(metadata, original_path=file_name)
            folder_parts = list(new_path.parent.parts)

            # \u83b7\u53d6\u91cd\u547d\u540d\u540e\u7684\u6587\u4ef6\u540d
            renamed_filename = new_path.name
            logger.info("\u8def\u5f84\u6574\u7406: %s -> %s", file_name, new_path)

            # \u5728139\u4e91\u76d8\u521b\u5efa\u5bf9\u5e94\u7684\u6587\u4ef6\u5939\u7ed3\u6784
            uploader = self.yun139_uploader
            parent_id = uploader.parent_id
            for folder_name in folder_parts:
                safe_name = re.sub(r'[\\/:*?"<>|]', "", folder_name)
                fid = uploader._get_or_create_folder(safe_name, parent_id)
                if fid:
                    parent_id = fid
                else:
                    logger.error(
                        "\u521b\u5efa\u6587\u4ef6\u5939\u5931\u8d25: %s (\u7236: %s)", safe_name, parent_id,
                    )
                    return

            # \u4f7f\u7528\u91cd\u547d\u540d\u540e\u7684\u6587\u4ef6\u540d\u8fdb\u884c\u79d2\u4f20
            upload_name = renamed_filename
            if self.app_mode and upload_name.lower().endswith(VIDEO_EXT):
                upload_name += ".jpg"

            client = uploader.client
            result = client.rapid_upload(
                sha256=sha256,
                size=file_size,
                filename=upload_name,
                parent_id=parent_id,
                app_mode=self.app_mode,
            )

            if result.get("success"):
                logger.info("\u79d2\u4f20\u6210\u529f: %s -> %s/%s", file_name, "/".join(folder_parts), upload_name)

                # \u5982\u679c\u4f7f\u7528\u4e86 app_mode \u4f2a\u88c5\uff0c\u9700\u8981\u5c06\u6587\u4ef6\u91cd\u547d\u540d\u56de\u539f\u59cb\u540d\u79f0
                if self.app_mode and upload_name != renamed_filename:
                    file_id = result.get("fileId")
                    if file_id:
                        try:
                            # \u6784\u9020 FileInfo \u5bf9\u8c61\u7528\u4e8e\u91cd\u547d\u540d
                            from ..upload.yun139 import FileInfo
                            from datetime import datetime

                            file_info = FileInfo(
                                id=file_id,
                                name=upload_name,  # \u5f53\u524d\u4e91\u76d8\u4e2d\u7684\u540d\u79f0\uff08\u5e26 .jpg\uff09
                                size=file_size,
                                is_folder=False,
                                created_time=datetime.now(),
                                modified_time=datetime.now(),
                            )

                            # \u91cd\u547d\u540d\u4e3a\u539f\u59cb\u6587\u4ef6\u540d\uff08\u4e0d\u5e26 .jpg\uff09
                            if client.rename(file_info, renamed_filename):
                                logger.info("\u91cd\u547d\u540d\u6210\u529f: %s -> %s", upload_name, renamed_filename)
                            else:
                                logger.warning("\u91cd\u547d\u540d\u5931\u8d25: %s -> %s", upload_name, renamed_filename)
                        except Exception as e:
                            logger.error("\u91cd\u547d\u540d\u65f6\u51fa\u9519: %s", e, exc_info=True)
                    else:
                        logger.warning("\u79d2\u4f20\u7ed3\u679c\u4e2d\u672a\u8fd4\u56de fileId\uff0c\u65e0\u6cd5\u91cd\u547d\u540d")
                else:
                    file_id = result.get("fileId")

                # \u751f\u6210 STRM \u6587\u4ef6
                if file_id and uploader.strm_server and uploader.strm_output_dir:
                    try:
                        logger.info("\u751f\u6210 STRM \u6587\u4ef6: %s", renamed_filename)
                        strm_url = uploader.generate_strm_url(
                            file_id=file_id,
                            file_name=renamed_filename,
                        )
                        if strm_url:
                            strm_path = uploader.generate_strm_file(
                                strm_url=strm_url,
                                file_name=renamed_filename,
                                folder_structure=folder_parts
                            )
                            if strm_path:
                                logger.info("STRM \u6587\u4ef6\u5df2\u751f\u6210: %s", strm_path)
                            else:
                                logger.warning("\u751f\u6210 STRM \u6587\u4ef6\u5931\u8d25")
                        else:
                            logger.warning("\u751f\u6210 STRM URL \u5931\u8d25")
                    except Exception as e:
                        logger.error("\u751f\u6210 STRM \u6587\u4ef6\u65f6\u51fa\u9519: %s", e, exc_info=True)
            else:
                logger.warning("\u79d2\u4f20\u5931\u8d25: %s, result=%s", file_name, result)
        except Exception as e:
            logger.error("\u5904\u7406 new_media \u5931\u8d25 (%s): %s", file_name, e, exc_info=True)
