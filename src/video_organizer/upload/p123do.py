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
# ...

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

# client = P123Client(TOKEN)
# # file = "F:\XunLeiDownLoad\FDM\瑞草洞.Law.and.the.City.2025.S01E01.1080p.DSNP.WEB-DL.H264.AAC.mkv"
# file = "F:\\XunLeiDownLoad\\media\\[Studio GreenTea] Silent Witch - Chinmoku no Majo no Kakushigoto [11][WebRip][hevc-10bit 1080p AAC][JPSC].mp4"
# file = os.path.normpath(file)
# # 调用函数计算MD5和大小
# file_md5 = calculate_md5(file)
# file_size = get_file_size(file)
# if file_md5 is not None and file_size is not None:
#     print(f"\n计算完成！")
#     print(f"文件大小 (file_size): {file_size} 字节")
#     print(f"文件 MD5 (file_md5): {file_md5}")
    
#     # 这里是您提供的原始上传代码，现在可以使用计算出的变量
#     # 假设 client 和其他变量已定义
#     # parent_id = 18656553
#     # duplicate = 0
#     # res = client.upload_file(file_path_to_check, file_md5, os.path.basename(file_path_to_check), file_size, parent_id, duplicate, async_=False)
#     # print("\n上传结果:", res)
# else:
#     print("\n文件计算失败，请检查文件路径是否正确。")
#     sys.exit(1) # 如果计算失败，退出程序
# file_name = "[Studio GreenTea] Silent Witch - Chinmoku no Majo no Kakushigoto [11][WebRip][hevc-10bit 1080p AAC][JPSC].mp4"
# parent_id = 18656553
# duplicate = 0
# # res = client.upload_file(file=file, file_name=file_name, parent_id=parent_id, duplicate=duplicate, async_=False)
# res = client.upload_file(file=file,file_md5=file_md5, file_name=file_name, file_size=file_size,parent_id=parent_id, duplicate=duplicate, async_=False)
# print(res)

import os
import hashlib
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
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
        upload_data = resp["data"]
        slice_size = int(upload_data.get("SliceSize", 200 * 1024 * 1024))
        
        if file_size > slice_size:
            print(f"[INFO] 开始分块上传: {target_name} ({file_size/1024/1024:.2f}MB)")
            return _upload_large_file(client, file_path, upload_data, target_name, file_size, slice_size, callback)
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
    'Connection': 'keep-alive',
    'Origin': 'https://www.123pan.com',
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
    callback=None
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
            slice_no = 1
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
                        upload_url = current_upload_url_resp["data"]["presignedUrls"][str(slice_no)]
                        
                        # 准备 Headers
                        headers = UPLOAD_HEADERS.copy()
                        # headers['Content-Length'] = str(num_to_upload) # requests会自动计算
                        
                        # 使用 requests 直接上传，避免 client.request 的 JSON 解析问题
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
                        print(f"[WARNING] 分片 {slice_no} 上传异常 ({retry_count}/{max_retries}): {error_msg}")
                        
                        if retry_count < max_retries:
                            # 针对 API 限制错误的特殊处理
                            if "tokens number has exceeded the limit" in error_msg:
                                print(f"[WARNING] 触发API频率限制，等待 30 秒后重试...")
                                time.sleep(30)
                            else:
                                time.sleep(5)
                            
                            try:
                                # pbar.write(f"[INFO] 重新获取分片 {slice_no} URL")
                                current_upload_url_resp = client.upload_prepare(upload_data)
                                if current_upload_url_resp.get("code") != 0:
                                    raise Exception(f"重新获取上传URL失败: {current_upload_url_resp.get('message')}")
                            except Exception as url_err:
                                print(f"[ERROR] 重新获取上传URL失败: {url_err}")
                                # 如果是 limit 错误，这里可能还会失败，但我们会继续重试循环
                                if "tokens number has exceeded the limit" in str(url_err):
                                     time.sleep(30)
                                     retry_count -= 1 # 这次获取URL失败不算在上传重试次数里？或者保持原样
                                raise
                        else:
                            pbar.write(f"[ERROR] 分片 {slice_no} 失败，达到最大重试次数")
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