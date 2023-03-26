import asyncio
import datetime
import logging
import os
from datetime import datetime, timedelta

import aiohttp
import tldextract
from motor.motor_asyncio import AsyncIOMotorClient


logging.basicConfig(level=logging.INFO)

proxy_schema = {
    '_id': str,
    'proxy': str,
    'type': str,
    'blocked_sites': [],
    'expiration_date': datetime
}


class ProxyRotator:
    proxies_collection = None
    session = None
    static_proxy_ids = {}
    rotating_proxy_counts = {}

    def __init__(self, proxy6_api_key: str, db_uri: str, auto_purchase_new: bool = False):
        self.purchase_enabled = auto_purchase_new
        self._proxy6_api_key = proxy6_api_key
        self._db_uri = db_uri

    async def static(self, method, url, headers, cookies, params, data, json_data):
        proxy = await self._get_static_proxy(url)
        return await self.request(proxy, method, url, headers, cookies, params, data, json_data)

    async def get_static(self, url):
        proxy = await self._get_static_proxy(url)
        return proxy['proxy']

    async def rotating(self, method, url, headers, cookies, params, data, json_data):
        proxy = await self._get_rotating_proxy(url)
        return await self.request(proxy, method, url, headers, cookies, params, data, json_data)

    async def get_rotating(self, url):
        proxy = await self._get_rotating_proxy(url)
        return proxy['proxy']

    async def request(self, proxy, method, url, headers, cookies, params, data, json_data):
        logging.info(f'Requesting {url} with {proxy["_id"]}')
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, cookies=cookies, params=params, data=data,
                                       json=json_data, proxy=proxy['proxy']) as response:

                if response.status in [502, 403]:
                    logging.info(f'Recieved {response.status}, marking {proxy["proxy"]} as blocked for {self._get_domain(url)}')
                    await self.update_blocked_sites(proxy, url)

                if response.status in [429]:
                    logging.info(f'Recieved {response.status}, indicating rate limiting on {proxy["proxy"]}. Rotating proxy.')
                    self.static_proxy_ids[self._get_domain(url)] = (await self._get_rotating_proxy(url))['_id']

                logging.info(f'Recieved STATUS: {response.status} CONTENT: {response.content_type} with {proxy["_id"]}')
                content = await response.read()
                response_headers = {key.lower():value for key, value in dict(response.headers).items()}
                response_headers.pop('content-encoding', None)
                response_headers.pop('content-length', None)

                return content, response.status, response_headers

    async def purchase_proxy(self):
        logging.info('Purchasing proxy')

        days = 30

        params = {
            'count': 1,
            'period': days,
            'country': 'ru',
            'version': 3,
            'type': 'http'
        }

        base_url = 'https://proxy6.net/api/'

        r = await self.session.get(base_url + self._proxy6_api_key + '/buy', params=params)
        if r.status == 200:
            j = await r.json()
            if j['status'] == 'yes':
                logging.info(f'Cost:{j["price"]}, Remaining Balance: {j["balance"]}')
                for id, proxy in j['list'].items():
                    id = id
                    proxy_ip = f'http://{proxy["user"]}:{proxy["pass"]}@{proxy["ip"]}:{proxy["port"]}'

                    types = {
                        '3': 'ipv4',
                        '4': 'ipv4',
                        '6': 'ipv6'
                    }

                    type = types[proxy['version']]
                    blocked_sites = []

                    expiration_date = datetime.utcnow() + timedelta(days=30)

                    logging.info(
                        f'Succesfully purchased proxy {id} {proxy_ip} {type} {blocked_sites} {expiration_date}')
                    await self._add_proxy(id, proxy_ip, type, blocked_sites, expiration_date)
            else:
                logging.error(f'Error fetching proxies {await r.text()}')

    async def _add_proxy(self, id, proxy, type, blocked_sites, expiration_date):
        proxy_data = proxy_schema.copy()
        proxy_data['_id'] = id
        proxy_data['proxy'] = proxy
        proxy_data['type'] = type
        proxy_data['blocked_sites'] = blocked_sites
        proxy_data['expiration_date'] = expiration_date
        await self.proxies_collection.insert_one(proxy_data)

    async def _get_static_proxy(self, url='', type='ipv4'):

        domain = self._get_domain(url)
        if domain not in self.static_proxy_ids:
            await self._update_static_proxy(url, type)

        proxy = await self._get_proxy_by_id(self.static_proxy_ids[domain])

        print(proxy['blocked_sites'])

        if domain in proxy['blocked_sites']:
            await self._update_static_proxy(url, type)
            proxy = await self._get_proxy_by_id(self.static_proxy_ids)

        return proxy

    async def _get_proxy_by_id(self, _id):
        return await self.proxies_collection.find_one({'_id': _id})

    async def _update_static_proxy(self, url='', type='ipv4'):
        domain = self._get_domain(url)
        logging.info(f'Getting new static proxy for {domain}')
        self.static_proxy_ids[domain] = (await self._get_proxy(url, type))['_id']
        logging.info(f'Assigned {self.static_proxy_ids[domain]} to {domain}')

    async def update_blocked_sites(self, proxy, url):
        domain = self._get_domain(url)
        if domain in self.static_proxy_ids:
            if self.static_proxy_ids[domain] == proxy['_id']:
                self.static_proxy_ids.pop(domain) # Remove proxy from our static proxies dictionary if it is blocked on that site

        await self.proxies_collection.update_one(
            {'_id': proxy['_id']},
            {'$push': {'blocked_sites': domain}}
        )

    async def _get_rotating_proxy(self, url='', type='ipv4'):
        domain = self._get_domain(url)
        if domain not in self.rotating_proxy_counts:
            self.rotating_proxy_counts[domain] = 0

        self.rotating_proxy_counts[domain] += 1

        if url is not None:
            query = {'blocked_sites': {'$ne': url}, 'type': type}

        cursor = self.proxies_collection.find(query)
        proxies = []
        async for doc in cursor:
            proxies.append(doc)

        return proxies[self.rotating_proxy_counts[domain] % len(proxies)]

    async def _get_proxy(self, url='', type='ipv4'):

        if url is not None:
            domain = self._get_domain(url)
            query = {'blocked_sites': {'$ne': domain}, 'type': type}

        proxy = await self.proxies_collection.find_one(query)

        if proxy is None and self.purchase_enabled:
            return await self.purchase_proxy()  # If we can't find an unblocked proxy we will buy a new one!

        return proxy

    async def _check_proxy_expired(self, proxy):
        current_time = datetime.datetime.utcnow()
        if proxy.get('expiration_date') and proxy['expiration_date'] < current_time:
            # If the proxy is expired, check and remove ALL expired proxies from the database
            await self._check_and_remove_expired_proxies()

    async def _check_and_remove_expired_proxies(self):
        # Get the current date and time
        current_time = datetime.datetime.utcnow()

        # Define the query to find expired proxies
        query = {'expiration_date': {'$lt': current_time}}

        # Delete all expired proxies that match the query
        result = await self.proxies_collection.delete_many(query)
        logging.info(f"Deleted {result.deleted_count} expired proxies.")

    async def _connect_to_db(self):
        client = AsyncIOMotorClient(self._db_uri)
        database = client['ProxyRotator']
        self.proxies_collection = database['proxies']

    async def _create_session(self):
        self.session = aiohttp.ClientSession()

    async def setup(self):
        await self._connect_to_db()
        await self._create_session()

    def _get_domain(self, url):
        return tldextract.extract(url).registered_domain


async def main():
    db_uri = os.environ.get('DB_URI')
    proxy6_api_key = os.environ.get('PROXY6')

    p = ProxyRotator(proxy6_api_key, db_uri)
    logging.basicConfig(level=logging.INFO)
    await p.setup()


    p._get_domain('https://item.taobao.com/item.htm?id=626235369969')
    proxy = await p._get_static_proxy('pandabuy.com')
    print(proxy)
    proxy = await p._get_static_proxy('pandabuy.com')
    print(proxy)
    proxy = await p._get_rotating_proxy('pandabuy.com')
    print(proxy)
    proxy = await p._get_rotating_proxy('pandabuy.com')
    print(proxy)

    # print(proxy)

    # await p._get_proxy()


if __name__ == '__main__':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
