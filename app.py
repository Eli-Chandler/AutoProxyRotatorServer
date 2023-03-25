from quart import Quart, request
from proxyrotator import ProxyRotator
import os

app = Quart(__name__)

db_uri = os.environ.get('DB_URI')
proxy6_api_key = os.environ.get('PROXY6')
token = os.environ.get('TOKEN') # Token needed for requests to be accepted

p = ProxyRotator(proxy6_api_key, db_uri, True)

@app.route('/', methods=['POST'])
async def proxy_request():



    payload = await request.get_json()

    request_token = payload.get('token', '')
    print(token, request_token)
    if request_token != token:
        return 'Bad Token', 403, {}

    proxy_method = payload.get('proxy_method')
    method = payload.get('method')
    url = payload.get('url')
    headers = payload.get('headers', None)
    cookies = payload.get('cookies', None)
    params = payload.get('params', None)
    data = payload.get('data', None)
    json_data = payload.get('json', None)

    if proxy_method == 'static':
        return await p.static(method, url, headers, cookies, params, data, json_data)
    if proxy_method == 'rotate':
        return await p.rotating(method, url, headers, cookies, params, data, json_data)

@app.before_serving
async def setup():
    await p.setup()


if __name__ == '__main__':
    app.run()