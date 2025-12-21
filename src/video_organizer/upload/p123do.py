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

# 以前的全局配置加载代码已移除，现在由外部传入配置
# CONFIG = load_config()
# TOKEN = CONFIG.get("token")

def calculate_md5(file_path, block_size=65536):
    """
    计算给定文件的MD5哈希值。
    
    Args:
        file_path (str): 文件的完整路径。
        block_size (int): 读取文件时的块大小，以字节为单位。
                          为了高效处理大文件，此函数会分块读取。
                          默认值 65536 (64KB) 是一个合理的选择。
    
    Returns:
        str or None: 文件的MD5哈希值（以十六进制字符串形式），
                     如果文件不存在或发生错误，则返回 None。
    """
    md5_hash = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(block_size), b""):
                md5_hash.update(block)
        return md5_hash.hexdigest()
    except FileNotFoundError:
        print(f"错误: 文件 '{file_path}' 不存在。")
        return None
    except IOError as e:
        print(f"错误: 读取文件 '{file_path}' 时发生IO错误: {e}")
        return None

def get_file_size(file_path):
    """
    获取给定文件的大小。
    
    Args:
        file_path (str): 文件的完整路径。
    
    Returns:
        int or None: 文件的大小（以字节为单位），如果文件不存在，则返回 None。
    """
    try:
        return os.path.getsize(file_path)
    except FileNotFoundError:
        print(f"错误: 文件 '{file_path}' 不存在。")
        return None
    except Exception as e:
        print(f"错误: 获取文件 '{file_path}' 大小时发生未知错误: {e}")
        return None

import os
import hashlib
import time
from pathlib import Path
from datetime import datetime
from typing import NoReturn, Optional, Dict, Any
from functools import wraps

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
                    print(f"[WARNING] 操作失败，尝试重试 {retries}/{max_retries}: {str(e)}")
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

def upload_file(
    client: Any,
    file_path: str,
    parent_id: int,
    new_name: Optional[str] = None,
    max_retries: int = 3,
    callback=None
) -> Optional[Dict[str, Any]]:
    """
    上传文件到123云盘（参考p123do.py upload修改）
    
    :param client: 已初始化的P123Client实例
    :param file_path: 本地文件路径
    :param parent_id: 目标文件夹ID
    :param new_name: 上传后的文件名（可选）
    :param max_retries: 最大重试次数（此处主要用于内部重试，函数整体重试逻辑如下）
    :return: 上传成功返回文件信息字典，失败返回None
    """
    file_path = Path(file_path)
    target_name = new_name or file_path.name
    # 简单的文件名清理
    target_name = re.sub(r'[\\/:*?"<>|]', "", target_name)
    
    file_size = file_path.stat().st_size
    
    print(f"[INFO] 开始计算文件MD5: {file_path}")
    file_md5 = calculate_md5(file_path)
    
    # 尝试秒传/初始化上传
    try:
        resp = client.upload_request({
            "etag": file_md5,
            "fileName": target_name,
            "size": file_size,
            "parentFileId": parent_id,
            "type": 0,
            "duplicate": 2,
        })
        
        # 简单检查响应
        if resp.get("code") != 0:
             raise Exception(f"上传请求失败: {resp.get('message')}")
        
        if resp.get("data", {}).get("Reuse"):
            print(f"[SUCCESS] 秒传成功: {target_name}")
            data = resp["data"]["Info"]
            return {
                "name": target_name,
                "size": file_size,
                "etag": data["Etag"],
                "keyflag": data["S3KeyFlag"],
                "fileid": str(data["FileId"]),
                "modify_time": int(datetime.now().timestamp())
            }
    except Exception as e:
        print(f"[ERROR] 秒传/初始化失败: {str(e)}")
        return None

    # 如果无法秒传，进行普通上传
    try:
        # 请求upload_list获取已经上传的块
        upload_list_resp = client.upload_list({
            "bucket": resp["data"]["Bucket"],
            "key": resp["data"]["Key"],
            "storageNode": resp["data"]["StorageNode"],
            "uploadId": resp["data"]["UploadId"],
        })
        len_uploaded_parts = 0
        if upload_list_resp.get("code") == 0:
            print(f"[INFO] upload_list_resp: {upload_list_resp}")
            # 验证Parts字段是否存在且不为None
            parts = upload_list_resp["data"].get("Parts")
            if parts is not None:
                len_uploaded_parts = len(parts)
                print(f"[INFO] 已上传分块: {parts}")
                print(f"[INFO] 已上传分块数: {len_uploaded_parts}")
            else:
                print(f"[INFO] 暂无已上传分块")
        else:
            print(f"[ERROR] 获取已上传分块失败: {upload_list_resp.get('message')}")
            print(f"[INFO] upload_list_resp: {upload_list_resp}")
        upload_data = resp["data"]
        slice_size = int(upload_data.get("SliceSize", 200 * 1024 * 1024))
        
        if file_size > slice_size:
            print(f"[INFO] 开始分块上传: {target_name} ({file_size/1024/1024:.2f}MB)")
            return _upload_large_file(client, file_path, upload_data, target_name, file_size, slice_size, callback, len_uploaded_parts)
        else:
            print(f"[INFO] 开始直接上传: {target_name}")
            return _upload_small_file(client, file_path, upload_data, target_name, callback)
            
    except Exception as e:
        print(f"[ERROR] 上传过程出错: {str(e)}")
        return None

# 定义通用的上传 Headers
UPLOAD_HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Origin': 'https://www.123pan.com',
    'Pragma': 'no-cache',
    'Referer': 'https://www.123pan.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'cross-site',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"'
}

def _upload_large_file(
    client: Any,
    file_path: Path,
    upload_data: Dict[str, Any],
    target_name: str,
    file_size: int,
    slice_size: int,
    callback=None,
    len_uploaded_parts: int = 0
) -> Dict[str, Any]:
    """分块上传大文件（带重试机制 + 进度条）"""
    total_parts = (file_size + slice_size - 1) // slice_size
    
    upload_request_kwargs = {
        "method": "PUT",
        "headers": {"authorization": ""},
        "timeout": 300,
    }

    # 使用tqdm创建进度条
    with tqdm(total=file_size, unit='B', unit_scale=True, desc=f"上传 {target_name}", ncols=80) as pbar:
        current_uploaded = 0
        with open(file_path, "rb") as f:
            slice_no = len_uploaded_parts + 1
            for chunk in iter(lambda: f.read(slice_size), b""):
                num_to_upload = len(chunk)

                # 准备分片信息
                upload_data["partNumberStart"] = slice_no
                upload_data["partNumberEnd"] = slice_no + 1
                
                # 获取上传URL
                try:
                    upload_url_resp = client.upload_prepare(upload_data)
                    if upload_url_resp.get("code") != 0:
                        raise Exception(f"获取分片 {slice_no} 上传URL失败: {upload_url_resp.get('message')}")
                except Exception as e:
                    pbar.write(f"[ERROR] 准备分片 {slice_no} 失败: {e}")
                    raise

                # 上传分片，失败时重试
                max_retries = 6
                retry_count = 0
                upload_success = False
                current_upload_url_resp = upload_url_resp
                
                while retry_count < max_retries and not upload_success:
                    try:
                        # 重试前，获取最新的已上传分块信息
                        if retry_count > 0:
                            try:
                                upload_list_resp = client.upload_list({
                                    "bucket": upload_data["Bucket"],
                                    "key": upload_data["Key"],
                                    "storageNode": upload_data["StorageNode"],
                                    "uploadId": upload_data["UploadId"],
                                })
                                if upload_list_resp.get("code") == 0:
                                    # 安全获取Parts字段，避免KeyError和TypeError
                                    parts = upload_list_resp["data"].get("Parts")
                                    if parts is not None:
                                        len_uploaded_parts = len(parts)
                                        print(f"[INFO] 重试前已上传分块: {parts}")
                                        print(f"[INFO] 重试前已上传分块数: {len_uploaded_parts}")
                                        # 更新当前分片号，跳过已上传的分块
                                        slice_no = len_uploaded_parts + 1
                                    else:
                                        print(f"[INFO] 重试前暂无已上传分块")
                            except Exception as list_err:
                                print(f"[WARNING] 获取已上传分块信息失败: {list_err}")
                        
                        # 在每次重试时重新获取当前分片的URL
                        # 如果是首次上传或之前没有重新获取过URL，则使用之前的current_upload_url_resp
                        # 否则使用重新获取的URL
                        if retry_count > 0:
                            try:
                                # 确保只重新获取当前失败分片的URL
                                upload_data["partNumberStart"] = slice_no
                                upload_data["partNumberEnd"] = slice_no + 1
                                
                                # 直接重新获取当前分片的URL
                                current_upload_url_resp = client.upload_prepare(upload_data)
                                if current_upload_url_resp.get("code") != 0:
                                    raise Exception(f"重新获取上传URL失败: {current_upload_url_resp.get('message')}")
                                print(f"[INFO] 成功重新获取分片 {slice_no} URL")
                            except Exception as url_err:
                                print(f"[ERROR] 重新获取上传URL失败: {url_err}")
                                if "tokens number has exceeded the limit" in str(url_err):
                                    print(f"[WARNING] 触发API频率限制，等待 30 秒后重试...")
                                    time.sleep(30)
                        
                        # 获取当前分片的上传URL
                        upload_url = current_upload_url_resp["data"]["presignedUrls"][str(slice_no)]
                        
                        # 准备 Headers
                        headers = UPLOAD_HEADERS.copy()
                        # headers['Content-Length'] = str(num_to_upload) # requests会自动计算
                        
                        # 尝试上传
                        response = requests.put(
                            upload_url,
                            data=chunk,
                            headers=headers,
                            timeout=300
                        )
                        response.raise_for_status() # 检查状态码
                        upload_success = True
                        del chunk # 显式释放内存
                    except Exception as upload_err:
                        retry_count += 1
                        error_msg = str(upload_err)
                        
                        if retry_count >= max_retries:
                            print(f"[ERROR] 分片 {slice_no} 失败，达到最大重试次数")
                            raise

                slice_no += 1
                pbar.update(num_to_upload)
                current_uploaded += num_to_upload
                if callback:
                    try:
                        callback(current_uploaded, file_size)
                    except Exception:
                        pass

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
                print(f"[WARNING] 合并文件失败 ({complete_count+1}/{complete_retries}): {complete_resp.get('message')}")
                complete_count += 1
                if complete_count < complete_retries:
                    time.sleep(5)
        except Exception as e:
            print(f"[WARNING] 合并文件请求异常 ({complete_count+1}/{complete_retries}): {e}")
            complete_count += 1
            if complete_count < complete_retries:
                time.sleep(5)
    
    if not complete_success:
        msg = complete_resp.get('message', '未知错误') if complete_resp else '请求失败'
        raise Exception(f"上传完成失败: {msg}")
    
    data = complete_resp.get("data", {}).get("file_info", {})
    return {
        "name": target_name,
        "size": file_size,
        "etag": data.get("Etag", ""),
        "keyflag": data.get("S3KeyFlag", ""),
        "fileid": str(data.get("FileId", "")),
        "modify_time": int(datetime.now().timestamp())
    }

def _upload_small_file(
    client: Any,
    file_path: Path,
    upload_data: Dict[str, Any],
    target_name: str,
    callback=None
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
                timeout=300
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
                print(f"[WARNING] {target_name} 上传失败，正在重试 ({retry_count}/{max_retries}): {upload_err}")
                time.sleep(5)  # 等待后重试
                
                # 重新获取上传URL
                try:
                    print(f"[INFO] 重新获取上传URL")
                    current_resp = client.upload_auth(upload_data)
                    if current_resp.get("code") != 0:
                        raise Exception(f"重新获取上传URL失败: {current_resp.get('message')}")
                except Exception as url_err:
                    print(f"[ERROR] 重新获取上传URL失败: {url_err}")
                    raise
            else:
                print(f"[ERROR] {target_name} 上传失败，已达到最大重试次数: {upload_err}")
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
        "modify_time": int(datetime.now().timestamp())
    }