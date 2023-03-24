# Auto Proxy Rotator Server

**WIP**

This is an asynchronous, fully automatic proxy server.

What does this mean? Instead of maintaining a proxy list, we can simply do this:


r = await session.get('https://www.example.com', proxy=)

And have everything handled for us internally!

* No more maintaing a proxy list
* No more checking if our proxies are expired
* No more manually buying proxies
* No more checking if our proxies are blocked

## Features

* This tool maintains a record of what sites each proxy has been blocked on, so when your proxy gets blocked on one domain, it will still be used for others!
* Either automatically rotate proxies using /rotate endpoint, or /static, to use the same proxy until it is blocked, and it will be automatically replaced
* Can be connected to proxy6 to automatically buy proxies (This is the cheapest proxy provider I have found)
