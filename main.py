import re
import time
import json

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse

import uvicorn
import requests

app = FastAPI(docs_url=None)


# 获取当前npm包最新版本
async def get_latest_version(repo):
    url = 'https://registry.npmjs.com/' + repo
    data = requests.get(url).json()
    return data['dist-tags']['latest']


def get_middle_str(content, start_str, end_str):
    pattern_str = r'%s(.+?)%s' % (start_str, end_str)
    pattern = re.compile(pattern_str, re.S)
    result = pattern.findall(content)
    return result[0]


async def purge_gcore_cdn(path):
    paths = {}
    paths['paths'] = []
    paths['paths'].append(path)
    paths = json.dumps(paths, ensure_ascii=False)
    url = 'https://api.gcorelabs.com/cdn/resources/150601/purge'
    headers = {
        'Authorization': '',
        'content-type': 'application/json'
    }
    request = requests.post(url, data=paths, headers=headers).json()
    request = {"code": "200",
               "msg": "We have submitted a refresh request to Gcore, please see the data returned by Gcore(Amiya-CDN)",
               "data": request, "time": str(int(time.time()))}
    request = json.dumps(request, ensure_ascii=False)
    return request


async def download_unpkg(repo, version, path):
    url = 'https://unpkg.com/' + repo + '@' + version + '/' + path
    data = requests.get(url)
    # 检测是否为200或者304
    if data.status_code == 200 or data.status_code == 304:
        return data
    else:
        return False


# 检测仓库封禁状态
async def ban_status(type, user, repo):
    if type == 'gh':
        url = 'https://assets.tnxg.whitenuo.cn/data/cdn-ban/gh.json'
        query = user + '/' + repo
    elif type == 'npm':
        url = 'https://assets.tnxg.whitenuo.cn/data/cdn-ban/npm.json'
        query = repo
    data = requests.get(url).json()
    if query in data:
        return True


async def download_github(user, repo, branch, path):
    url = 'https://raw.githubusercontent.com/' + \
          user + '/' + repo + '/' + branch + '/' + path
    data = requests.get(url)
    size = data.headers['Content-Length']
    # 将size转换为MB
    size = round(int(size) / 1024 / 1024, 2)
    # 如果文件大小大于25MB则返回False
    if size > 25:
        return False
    # 检测是否为200或者304
    if data.status_code == 200 or data.status_code == 304:
        return data
    else:
        return False


async def download_gravatar(hash):
    url = 'https://gravatar.com/avatar/' + hash
    data = requests.get(url)
    return data


# 获取github仓库默认分支
async def get_github_branch(user, repo):
    url = 'https://api.github.com/repos/' + user + '/' + repo
    data = requests.get(url).json()
    return data['default_branch']


# 设置全局返回头
@app.middleware("http")
async def add_cors_headers(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["service"] = "Preliminary Rodesisland Terminal System(PRTS)"
    return response


@app.get("/{path:path}")
async def root(request: Request, path: str):
    try:
        # 获得请求url
        url = str(request.url)
        # 获得请求域名
        domain = request.headers.get('host')
        # 获取请求的协议
        protocol = re.findall(r'(.*?://)', url)[0]
        # 获得回源方式
        source = re.findall(r'(.*?)/', path)[0]
    except:
        protocol = None
        source = None

    # Unpkg回源
    if source == 'npm':
        try:
            # 获得仓库和版本
            url = path.replace(source + '/', '')
            # 检测是否有@符号
            if '@' in url:
                repo = re.findall(r'(.*?)@', url)[0]
                version = re.findall(r'@(.*?)/', url)[0]
                paths = re.findall(r'/(.*)', url)[0]
                data = await download_unpkg(repo, version, paths)
            else:
                repo = re.findall(r'(.*?)/', url)[0]
                version = 'latest'
                paths = re.findall(r'/(.*?)', url)[0]
            if version == 'latest':
                version = await get_latest_version(repo)
                url = protocol + domain + '/npm/' + repo + '@' + version + '/' + paths
                return RedirectResponse(url=url)
            if await ban_status('npm', None, repo):
                return JSONResponse(
                    status_code=403,
                    content={"code": "403", "msg": "Repository is banned(Amiya-CDN)", "time": str(int(time.time()))})
            data = await download_unpkg(repo, version, paths)
            if data:
                response = Response(content=data.content,
                                    media_type=data.headers['Content-Type'])
                response.headers["amiyacdn-npm-repo"] = repo
                response.headers["amiyacdn-npm-version"] = version
                response.headers["amiyacdn-npm"] = 'npm'
                # 返回数据并携带头部
                return response
            else:
                return JSONResponse(
                    status_code=403,
                    content={"code": "404", "msg": "File does not exist(Amiya-CDN)", "time": str(int(time.time()))})
        except:
            return JSONResponse(
                status_code=502,
                content={"code": "502", "msg": "Our Origin server has encountered an unknown exception(Amiya-CDN)",
                         "time": str(int(time.time()))})

    # Github回源
    elif source == 'gh':
        try:
            # 获得仓库和版本
            url = path.replace(source + '/', '')
            # 检测是否有@符号
            if '@' in url:
                user = re.findall(r'gh/(.*?)/', path)[0]
                repo = re.findall(r'/(.*?)@', url)[0]
                branch = re.findall(r'@(.*?)/', url)[0]
                paths = url.split(branch + '/')[1]
            else:
                user = re.findall(r'gh/(.*?)/', path)[0]
                repo = re.findall(user + r'/(.*?)/', url)[0]
                branch = await get_github_branch(user, repo)
                paths = url.split(repo + '/')[1]
            if await ban_status('gh', user, repo):
                return JSONResponse(
                    status_code=403,
                    content={"code": "403", "msg": "Repository is banned(Amiya-CDN)", "time": str(int(time.time()))})
            data = await download_github(user, repo, branch, paths)
            if data:
                response = Response(content=data.content,
                                    media_type=data.headers['Content-Type'])
                response.headers["amiyacdn-gh-repo"] = repo
                response.headers["amiyacdn-gh-branch"] = branch
                response.headers["amiyacdn-source"] = 'github'
            else:
                return JSONResponse(
                    status_code=403,
                    content={"code": "404", "msg": "File does not exist or file is larger than 25MB(Amiya-CDN)",
                             "time": str(int(time.time()))})
            return response
        except:
            return JSONResponse(
                status_code=502,
                content={"code": "502", "msg": "Our Origin server has encountered an unknown exception(Amiya-CDN)",
                         "time": str(int(time.time()))})

    # Gravatar 回源
    elif source == 'avatar':
        try:
            hash = re.findall(r'avatar/(.*)', path)[0]
            data = await download_gravatar(hash)
            if data:
                response = Response(content=data.content,
                                    media_type=data.headers['Content-Type'])
                response.headers["amiyacdn-source"] = 'gravatar'
            else:
                return JSONResponse(
                    status_code=403,
                    content={"code": "404", "msg": "File does not exist(Amiya-CDN)", "time": str(int(time.time()))})
            return response
        except:
            return JSONResponse(
                status_code=502,
                content={"code": "502", "msg": "Our Origin server has encountered an unknown exception(Amiya-CDN)",
                         "time": str(int(time.time()))})

    # 刷新Gcore CDN缓存
    elif source == 'purge':
        source2 = re.findall(r'purge/(.*?)/', path)[0]
        if source2 == 'npm':
            paths = '/npm/' + re.findall(r'npm/(.*)', path)[0]
            return Response(content=await purge_gcore_cdn(paths))
        elif source2 == 'gh':
            paths = '/gh/' + re.findall(r'gh/(.*)', path)[0]
            return Response(content=await purge_gcore_cdn(paths))
    else:
        return JSONResponse(status_code=403, content={"code": "404", "msg": "Origin does not exist(Amiya-CDN)",
                                                      "time": str(int(time.time()))})


if __name__ == '__main__':
    uvicorn.run('main:app', host='0.0.0.0', proxy_headers=True,
                reload=True, forwarded_allow_ips='*')
