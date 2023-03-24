# Auto Proxy Rotator Server

**WIP**

This is an asynchronous, fully automatic proxy server.

What does this mean? Instead of maintaing a proxy list, we can simply do this:

r = await session.get('https://www.example.com', proxy='http://your_proxy_server/rotate')

And have everything handled for us internally!

* No more maintaing a proxy list
* No more checking if our proxies are expired
* No more manually buying proxies
