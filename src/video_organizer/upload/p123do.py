from p123client import P123Client
from p123client.tool import get_downurl
import json as json1
import os

# from blacksheep import json, redirect, Application, Request
import hashlib
import os
import sys
import re
import requests  # 引入 requests
from tqdm import tqdm  # 引入进度条库
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
import time  # 引入时间模块用于重试延迟
import random  # 引入随机模块用于退避抖动
import os
import hashlib
import time
from pathlib import Path
from datetime import datetime
from typing import NoReturn, Optional, Dict, Any
from functools import wraps
from colorama import Fore, init

# 初始化 colorama
init(autoreset=True)


def retry(max_retries=3, delay=5):
    """重试装饰器"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    print(
                        f"[WARNING] 操作失败，尝试重试 {retries}/{max_retries}: {str(e)}"
                    )
                    if retries < max_retries:
                        time.sleep(delay)
                    else:
                        raise

        return wrapper

    return decorator


def calculate_md5(file_path: str, chunk_size=4096) -> str:
    """计算文件MD5"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def get_file_size(file_path: str) -> int:
    """获取文件大小（字节）"""
    return Path(file_path).stat().st_size


def upload_file(
    client: Any,
    file_path: str,
    parent_id: int,
    new_name: Optional[str] = None,
    max_retries: int = 3,
    callback=None,
    max_workers: int = 2,
) -> Optional[Dict[str, Any]]:
    """
    上传文件到123云盘（参考p123do.py upload修改）

    :param client: 已初始化的P123Client实例
    :param file_path: 本地文件路径
    :param parent_id: 目标文件夹ID
    :param new_name: 上传后的文件名（可选）
    :param max_retries: 最大重试次数（此处主要用于内部重试，函数整体重试逻辑如下）
    :param callback: 进度回调函数
    :param max_workers: 最大并发上传工作线程数，默认2
    :return: 上传成功返回文件信息字典，失败返回None
    """
    file_path = Path(file_path)
    target_name = new_name or file_path.name
    # 简单的文件名清理
    target_name = re.sub(r'[\\/:*?"<>|]', "", target_name)

    file_size = file_path.stat().st_size

    # 记录MD5计算开始时间
    md5_start_time = time.time()

    print(
        f"\n{Fore.CYAN}📁{Fore.RESET} {Fore.YELLOW}开始计算文件MD5{Fore.RESET}: {Fore.MAGENTA}{file_path.name}{Fore.RESET}"
    )
    file_md5 = calculate_md5(file_path)

    # 记录MD5计算结束时间
    md5_end_time = time.time()
    md5_time = md5_end_time - md5_start_time
    print(
        f"{Fore.GREEN}✓{Fore.RESET} MD5计算完成: {Fore.YELLOW}{md5_time:.2f} 秒{Fore.RESET}"
    )

    # 记录实际上传开始时间（排除MD5计算时间）
    upload_start_time = time.time()

    # 尝试秒传/初始化上传
    try:
        resp = client.upload_request(
            {
                "etag": file_md5,
                "fileName": target_name,
                "size": file_size,
                "parentFileId": parent_id,
                "type": 0,
                "duplicate": 2,
            }
        )

        # 简单检查响应
        if resp.get("code") != 0:
            raise Exception(f"上传请求失败: {resp.get('message')}")

        if resp.get("data", {}).get("Reuse"):
            print(
                f"\n{Fore.GREEN}⚡{Fore.RESET} {Fore.CYAN}秒传成功{Fore.RESET}: {Fore.YELLOW}{target_name}{Fore.RESET}"
            )
            data = resp["data"]["Info"]

            # 记录上传结束时间
            end_time = time.time()
            upload_time = end_time - upload_start_time  # 使用upload_start_time

            # 计算平均速度（使用实际上传数据量和实际上传时间）
            avg_speed = file_size / upload_time if upload_time > 0 else 0

            # 格式化输出统计信息
            print(f"\n{Fore.CYAN}{'='*50}{Fore.RESET}")
            print(
                f"{Fore.GREEN}✓{Fore.RESET} {Fore.CYAN}秒传成功{Fore.RESET}: {Fore.YELLOW}{target_name}{Fore.RESET}"
            )
            print(f"{Fore.CYAN}{'='*50}{Fore.RESET}")
            print(f"{Fore.CYAN}📊 上传统计信息{Fore.RESET}")
            print(
                f"  {Fore.CYAN}文件大小:{Fore.RESET} {Fore.MAGENTA}{file_size / (1024 * 1024):.2f} MB{Fore.RESET}"
            )
            print(
                f"  {Fore.CYAN}MD5耗时:{Fore.RESET} {Fore.YELLOW}{md5_time:.2f} 秒{Fore.RESET}"
            )
            print(
                f"  {Fore.CYAN}上传耗时:{Fore.RESET} {Fore.YELLOW}{upload_time:.2f} 秒{Fore.RESET}"
            )
            print(
                f"  {Fore.CYAN}平均速度:{Fore.RESET} {Fore.GREEN}{avg_speed / (1024 * 1024):.2f} MB/s{Fore.RESET}"
            )
            print(f"{Fore.CYAN}{'='*50}{Fore.RESET}\n")

            return {
                "name": target_name,
                "size": file_size,
                "etag": data["Etag"],
                "keyflag": data["S3KeyFlag"],
                "fileid": str(data["FileId"]),
                "modify_time": int(datetime.now().timestamp()),
                "upload_time": upload_time,
                "avg_speed": avg_speed,
            }
    except Exception as e:
        print(f"[ERROR] 秒传/初始化失败: {str(e)}")
        return None

    # 如果无法秒传，进行普通上传
    try:
        # 请求upload_list获取已经上传的块
        upload_list_resp = client.upload_list(
            {
                "bucket": resp["data"]["Bucket"],
                "key": resp["data"]["Key"],
                "storageNode": resp["data"]["StorageNode"],
                "uploadId": resp["data"]["UploadId"],
            }
        )
        len_uploaded_parts = 0
        uploaded_part_numbers = set()  # 已上传的分块编号集合
        upload_data = resp["data"]
        slice_size = int(upload_data.get("SliceSize", 200 * 1024 * 1024))
        total_parts = (
            file_size + slice_size - 1
        ) // slice_size  # 必须在slice_size之后定义

        if upload_list_resp.get("code") == 0:
            # 验证Parts字段是否存在且不为None
            parts = upload_list_resp["data"].get("Parts")
            if parts is not None:
                len_uploaded_parts = len(parts)
                # 提取已上传的分块编号（转换为整数，避免字符串和整数比较问题）
                uploaded_part_numbers = {int(part.get("PartNumber")) for part in parts}
                print(f"[INFO] 已上传分块: {parts}")
                print(f"[INFO] 已上传分块数: {len_uploaded_parts}")
                print(f"[INFO] 已上传分块编号: {sorted(uploaded_part_numbers)}")
                # 找出缺失的分块
                missing_parts = [
                    i
                    for i in range(1, total_parts + 1)
                    if i not in uploaded_part_numbers
                ]
                if missing_parts:
                    print(f"[INFO] 缺失分块: {missing_parts}")
            else:
                print(f"[INFO] 暂无已上传分块")
        else:
            print(f"[ERROR] 获取已上传分块失败: {upload_list_resp.get('message')}")
            print(f"[INFO] upload_list_resp: {upload_list_resp}")

        if file_size > slice_size:
            print(
                f"\n{Fore.CYAN}🚀{Fore.RESET} {Fore.YELLOW}开始分块上传{Fore.RESET}: {Fore.MAGENTA}{target_name}{Fore.RESET} ({Fore.CYAN}{file_size/1024/1024:.2f}MB{Fore.RESET})"
            )
            result = _upload_large_file(
                client,
                file_path,
                upload_data,
                target_name,
                file_size,
                slice_size,
                callback,
                uploaded_part_numbers,  # 传递已上传分块编号集合
                max_workers,
            )
        else:
            print(
                f"\n{Fore.CYAN}🚀{Fore.RESET} {Fore.YELLOW}开始直接上传{Fore.RESET}: {Fore.MAGENTA}{target_name}{Fore.RESET}"
            )
            result = _upload_small_file(
                client, file_path, upload_data, target_name, callback
            )

        # 记录上传结束时间
        end_time = time.time()
        upload_time = (
            end_time - upload_start_time
        )  # 使用upload_start_time，排除MD5计算时间

        # 计算平均速度（使用实际上传数据量和实际上传时间，排除MD5计算时间）
        avg_speed = file_size / upload_time if upload_time > 0 else 0

        # 格式化输出统计信息
        print(f"\n{Fore.CYAN}{'='*50}{Fore.RESET}")
        print(
            f"{Fore.GREEN}✓{Fore.RESET} {Fore.CYAN}上传成功{Fore.RESET}: {Fore.YELLOW}{target_name}{Fore.RESET}"
        )
        print(f"{Fore.CYAN}{'='*50}{Fore.RESET}")
        print(f"{Fore.CYAN}📊 上传统计信息{Fore.RESET}")
        print(
            f"  {Fore.CYAN}文件大小:{Fore.RESET} {Fore.MAGENTA}{file_size / (1024 * 1024):.2f} MB{Fore.RESET}"
        )
        print(
            f"  {Fore.CYAN}MD5耗时:{Fore.RESET} {Fore.YELLOW}{md5_time:.2f} 秒{Fore.RESET}"
        )
        print(
            f"  {Fore.CYAN}上传耗时:{Fore.RESET} {Fore.YELLOW}{upload_time:.2f} 秒{Fore.RESET}"
        )
        print(
            f"  {Fore.CYAN}平均速度:{Fore.RESET} {Fore.GREEN}{avg_speed / (1024 * 1024):.2f} MB/s{Fore.RESET}"
        )
        print(f"{Fore.CYAN}{'='*50}{Fore.RESET}\n")

        return result
    except Exception as e:
        print(f"[ERROR] 上传过程出错: {str(e)}")
        return None


# 定义通用的上传 Headers
UPLOAD_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Origin": "https://www.123pan.com",
    "Pragma": "no-cache",
    "Referer": "https://www.123pan.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


def _upload_single_chunk(
    client: Any,
    file_path: Path,
    upload_data: Dict[str, Any],
    slice_no: int,
    chunk_data: bytes,
    pbar: tqdm,
    lock: threading.Lock,
    callback=None,
) -> int:
    """上传单个分片（线程安全）"""
    max_retries = 8  # 增加重试次数
    initial_backoff = 1  # 初始退避时间（秒）
    upload_success = False
    current_upload_url_resp = None
    upload_session = None

    try:
        # 创建会话以复用连接，提升性能
        upload_session = requests.Session()

        for retry_count in range(max_retries):
            try:
                # 准备分片信息
                upload_data["partNumberStart"] = slice_no
                upload_data["partNumberEnd"] = slice_no + 1

                # 获取上传URL
                if retry_count == 0 or current_upload_url_resp is None:
                    try:
                        current_upload_url_resp = client.upload_prepare(upload_data)
                        if current_upload_url_resp.get("code") != 0:
                            raise Exception(
                                f"获取分片 {slice_no} 上传URL失败: {current_upload_url_resp.get('message')}"
                            )
                    except Exception as e:
                        error_msg = f"[ERROR] 准备分片 {slice_no} 失败: {e}"
                        print(error_msg)
                        raise

                # 获取当前分片的上传URL
                upload_url = current_upload_url_resp["data"]["presignedUrls"][
                    str(slice_no)
                ]

                # 准备 Headers
                headers = UPLOAD_HEADERS.copy()
                # 添加 Content-Length 以避免额外的网络请求
                headers["Content-Length"] = str(len(chunk_data))

                # 尝试上传
                response = upload_session.put(
                    upload_url,
                    data=chunk_data,
                    headers=headers,
                    timeout=(
                        180,
                        900,
                    ),  # (连接超时, 读取超时) - 进一步增加读取超时到900秒
                    stream=False,
                )

                # 检查状态码
                response.raise_for_status()

                # 验证上传是否成功
                if response.status_code == 200:
                    upload_success = True

                    # 更新进度条（线程安全）
                    with lock:
                        pbar.update(len(chunk_data))
                        if callback:
                            try:
                                callback(pbar.n, pbar.total)
                            except Exception:
                                pass

                    # 及时释放内存
                    uploaded_size = len(chunk_data)
                    del chunk_data
                    return uploaded_size
                else:
                    raise Exception(f"上传返回非200状态码: {response.status_code}")

            except requests.exceptions.Timeout as e:
                # 超时异常特殊处理
                error_msg = f"[ERROR] 分片 {slice_no} 上传超时: {e}"
                print(
                    f"{Fore.RED}⏱️{Fore.RESET} {Fore.YELLOW}分片 {slice_no} 上传超时{Fore.RESET}: {e}"
                )

            except requests.exceptions.ConnectionError as e:
                # 网络连接异常特殊处理
                error_msg = f"[ERROR] 分片 {slice_no} 网络连接失败: {e}"
                print(
                    f"{Fore.RED}🔌{Fore.RESET} {Fore.YELLOW}分片 {slice_no} 网络连接失败{Fore.RESET}: {e}"
                )

            except Exception as upload_err:
                # 其他异常
                error_msg = str(upload_err)
                print(
                    f"{Fore.YELLOW}⚠️{Fore.RESET} 分片 {slice_no} 上传失败 ({retry_count + 1}/{max_retries}): {error_msg}"
                )

            if retry_count < max_retries - 1:
                # 指数退避 + 随机抖动，避免多个线程同时重试
                backoff_time = initial_backoff * (2**retry_count) + random.uniform(0, 1)
                print(
                    f"{Fore.CYAN}⏳{Fore.RESET} 分片 {slice_no} 将在 {Fore.YELLOW}{backoff_time:.1f}{Fore.RESET} 秒后重试"
                )
                time.sleep(backoff_time)
            else:
                # 最后一次重试失败
                final_error_msg = f"分片 {slice_no} 上传失败，已达到最大重试次数"
                print(
                    f"{Fore.RED}✗{Fore.RESET} {Fore.YELLOW}{final_error_msg}{Fore.RESET}"
                )
                raise Exception(final_error_msg)

    finally:
        # 关闭会话，释放资源
        if upload_session:
            upload_session.close()

    return 0


def _upload_large_file(
    client: Any,
    file_path: Path,
    upload_data: Dict[str, Any],
    target_name: str,
    file_size: int,
    slice_size: int,
    callback=None,
    uploaded_part_numbers: Optional[set] = None,  # 已上传的分块编号集合
    max_workers: int = 2,
) -> Dict[str, Any]:
    """分块上传大文件（多线程并发 + 重试机制 + 进度条）"""
    if uploaded_part_numbers is None:
        uploaded_part_numbers = set()

    total_parts = (file_size + slice_size - 1) // slice_size
    upload_request_kwargs = {
        "method": "PUT",
        "headers": {"authorization": ""},
        "timeout": 300,
    }

    # 动态调整并发数：根据总大小和分块数动态确定并发数
    # 对于超大文件，避免内存占用过高
    optimal_workers = min(
        max_workers,  # 不超过用户指定的最大并发数
        total_parts,  # 不超过总分块数
        max(2, os.cpu_count() + 2),  # 至少2个，最多CPU核心数+2
    )
    print(
        f"{Fore.CYAN}ℹ️{Fore.RESET} 使用 {Fore.YELLOW}{optimal_workers}{Fore.RESET} 个线程并发上传 {Fore.YELLOW}{total_parts}{Fore.RESET} 个分片"
    )

    # 创建线程锁用于进度条更新
    lock = threading.Lock()

    # 使用tqdm创建进度条（包含速度显示）
    # 计算已上传的字节数
    uploaded_bytes = len(uploaded_part_numbers) * slice_size
    with tqdm(
        total=file_size,
        unit="B",
        unit_scale=True,
        desc=f"上传 {target_name}",
        ncols=100,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
    ) as pbar:
        # 设置已上传的进度
        pbar.update(uploaded_bytes)

        # 使用线程池并发上传 - 真正的懒加载分片（仅在需要时读取）
        with ThreadPoolExecutor(max_workers=optimal_workers) as executor:
            futures = []

            # 计算需要上传的分块列表（排除已上传的）
            slices_to_upload = [
                i for i in range(1, total_parts + 1) if i not in uploaded_part_numbers
            ]
            print(f"[INFO] 需要上传的分块: {slices_to_upload}")

            # 提交所有分片任务（只提交元数据，不立即读取数据）
            for slice_no in slices_to_upload:
                future = executor.submit(
                    _upload_single_chunk_lazy,  # 使用懒加载版本的上传函数
                    client,
                    file_path,
                    upload_data.copy(),  # 复制upload_data避免线程间冲突
                    slice_no,
                    slice_size,  # 传递分片大小
                    pbar,
                    lock,
                    callback,
                )
                futures.append((future, slice_no))

            # 等待所有任务完成
            success_count = 0
            error_count = 0

            for future, slice_no in futures:
                try:
                    uploaded_size = future.result()
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    print(f"\n{Fore.RED}✗{Fore.RESET} 分片 {slice_no} 上传失败: {e}")
                    # 取消所有未完成的任务
                    for f, _ in futures:
                        if not f.done():
                            f.cancel()
                    raise Exception(
                        f"上传失败: 已上传 {success_count} 个分块，失败 {error_count} 个分块"
                    )

    # 完成上传
    upload_data["isMultipart"] = True

    complete_retries = 3
    complete_count = 0
    complete_success = False
    complete_resp = None

    while complete_count < complete_retries and not complete_success:
        try:
            complete_resp = client.upload_complete(upload_data)
            if complete_resp.get("code") == 0:
                complete_success = True
            else:
                print(
                    f"[WARNING] 合并文件失败 ({complete_count+1}/{complete_retries}): {complete_resp.get('message')}"
                )
                complete_count += 1
                if complete_count < complete_retries:
                    time.sleep(5)
        except Exception as e:
            print(
                f"[WARNING] 合并文件请求异常 ({complete_count+1}/{complete_retries}): {e}"
            )
            complete_count += 1
            if complete_count < complete_retries:
                time.sleep(5)

    if not complete_success:
        msg = complete_resp.get("message", "未知错误") if complete_resp else "请求失败"
        raise Exception(f"上传完成失败: {msg}")

    data = complete_resp.get("data", {}).get("file_info", {})
    return {
        "name": target_name,
        "size": file_size,
        "etag": data.get("Etag", ""),
        "keyflag": data.get("S3KeyFlag", ""),
        "fileid": str(data.get("FileId", "")),
        "modify_time": int(datetime.now().timestamp()),
    }


def _upload_small_file(
    client: Any,
    file_path: Path,
    upload_data: Dict[str, Any],
    target_name: str,
    callback=None,
) -> Dict[str, Any]:
    """上传小文件（带重试机制）"""
    resp = client.upload_auth(upload_data)
    if resp.get("code") != 0:
        raise Exception(f"获取上传授权失败: {resp.get('message', '未知错误')}")

    upload_request_kwargs = {
        "method": "PUT",
        "headers": {"authorization": ""},
        "timeout": 300,
    }

    with open(file_path, "rb") as f:
        file_data = f.read()

    # 上传文件，失败时重试
    max_retries = 6
    retry_count = 0
    upload_success = False
    current_resp = resp

    while retry_count < max_retries and not upload_success:
        try:
            # 准备 Headers
            headers = UPLOAD_HEADERS.copy()

            # 使用 requests 直接上传
            response = requests.put(
                current_resp["data"]["presignedUrls"]["1"],
                data=file_data,
                headers=headers,
                timeout=600,  # 增加超时时间到600秒
            )
            response.raise_for_status()
            upload_success = True
            if callback:
                try:
                    callback(os.path.getsize(file_path), os.path.getsize(file_path))
                except Exception:
                    pass
        except Exception as upload_err:
            retry_count += 1
            if retry_count < max_retries:
                print(
                    f"[WARNING] {target_name} 上传失败，正在重试 ({retry_count}/{max_retries}): {upload_err}"
                )
                time.sleep(5)  # 等待后重试

                # 重新获取上传URL
                try:
                    print(f"[INFO] 重新获取上传URL")
                    current_resp = client.upload_auth(upload_data)
                    if current_resp.get("code") != 0:
                        raise Exception(
                            f"重新获取上传URL失败: {current_resp.get('message')}"
                        )
                except Exception as url_err:
                    print(f"[ERROR] 重新获取上传URL失败: {url_err}")
                    raise
            else:
                print(
                    f"[ERROR] {target_name} 上传失败，已达到最大重试次数: {upload_err}"
                )
                raise

    upload_data["isMultipart"] = False
    complete_resp = client.upload_complete(upload_data)

    if complete_resp.get("code") != 0:
        raise Exception(f"上传完成失败: {complete_resp.get('message', '未知错误')}")

    data = complete_resp.get("data", {}).get("file_info", {})
    return {
        "name": target_name,
        "size": os.path.getsize(file_path),
        "etag": data.get("Etag", ""),
        "keyflag": data.get("S3KeyFlag", ""),
        "fileid": str(data.get("FileId", "")),
        "modify_time": int(datetime.now().timestamp()),
    }


# 添加懒加载版本的分片上传函数
def _upload_single_chunk_lazy(
    client: Any,
    file_path: Path,
    upload_data: Dict[str, Any],
    slice_no: int,
    slice_size: int,
    pbar: tqdm,
    lock: threading.Lock,
    callback=None,
) -> int:
    """上传单个分片（懒加载版本，仅在需要时读取文件数据）"""
    max_retries = 8  # 增加重试次数
    initial_backoff = 1  # 初始退避时间（秒）
    upload_success = False
    current_upload_url_resp = None
    upload_session = None

    try:
        # 创建会话以复用连接，提升性能
        upload_session = requests.Session()

        for retry_count in range(max_retries):
            try:
                # 计算当前分片的偏移量
                offset = (slice_no - 1) * slice_size

                # 懒加载：仅在需要上传时读取文件数据
                with open(file_path, "rb") as f:
                    f.seek(offset)
                    chunk_data = f.read(slice_size)

                if not chunk_data:
                    raise Exception(f"分片 {slice_no} 数据为空")

                # 准备分片信息
                upload_data["partNumberStart"] = slice_no
                upload_data["partNumberEnd"] = slice_no + 1

                # 获取上传URL
                if retry_count == 0 or current_upload_url_resp is None:
                    try:
                        current_upload_url_resp = client.upload_prepare(upload_data)
                        if current_upload_url_resp.get("code") != 0:
                            raise Exception(
                                f"获取分片 {slice_no} 上传URL失败: {current_upload_url_resp.get('message')}"
                            )
                    except Exception as e:
                        error_msg = f"[ERROR] 准备分片 {slice_no} 失败: {e}"
                        print(error_msg)
                        raise

                # 获取当前分片的上传URL
                upload_url = current_upload_url_resp["data"]["presignedUrls"][
                    str(slice_no)
                ]
                # print(f"[INFO] 分片 {slice_no} 上传URL: {upload_url}")

                # 准备 Headers
                headers = UPLOAD_HEADERS.copy()
                # 添加 Content-Length 以避免额外的网络请求
                headers["Content-Length"] = str(len(chunk_data))

                # 尝试上传
                response = upload_session.put(
                    upload_url,
                    data=chunk_data,
                    headers=headers,
                    timeout=(
                        180,
                        900,
                    ),  # (连接超时, 读取超时) - 进一步增加读取超时到900秒
                    stream=False,
                )

                # 检查状态码
                response.raise_for_status()

                # 验证上传是否成功
                if response.status_code == 200:
                    upload_success = True

                    # 更新进度条（线程安全）
                    with lock:
                        pbar.update(len(chunk_data))
                        if callback:
                            try:
                                callback(pbar.n, pbar.total)
                            except Exception:
                                pass

                    # 及时释放内存
                    del chunk_data
                    return slice_size
                else:
                    raise Exception(f"上传返回非200状态码: {response.status_code}")

            except requests.exceptions.Timeout as e:
                # 超时异常特殊处理
                error_msg = f"[ERROR] 分片 {slice_no} 上传超时: {e}"
                print(error_msg)

            except requests.exceptions.ConnectionError as e:
                # 网络连接异常特殊处理
                error_msg = f"[ERROR] 分片 {slice_no} 网络连接失败: {e}"
                print(error_msg)

            except Exception as upload_err:
                # 其他异常
                error_msg = str(upload_err)
                print(
                    f"[WARNING] 分片 {slice_no} 上传失败 ({retry_count + 1}/{max_retries}): {error_msg}"
                )

            if retry_count < max_retries - 1:
                # 指数退避 + 随机抖动，避免多个线程同时重试
                backoff_time = initial_backoff * (2**retry_count) + random.uniform(0, 1)
                print(f"[INFO] 分片 {slice_no} 将在 {backoff_time:.1f} 秒后重试")
                time.sleep(backoff_time)
            else:
                # 最后一次重试失败
                final_error_msg = f"分片 {slice_no} 上传失败，已达到最大重试次数"
                print(f"[ERROR] {final_error_msg}")
                raise Exception(final_error_msg)

    finally:
        # 关闭会话，释放资源
        if upload_session:
            upload_session.close()

    return 0
