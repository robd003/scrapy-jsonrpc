import logging
import six

from twisted.web import server, resource

from scrapy.exceptions import NotConfigured
from scrapy import signals
from scrapy.utils.reactor import listen_tcp

from scrapy_jsonrpc.jsonrpc import jsonrpc_server_call
from scrapy_jsonrpc.serialize import ScrapyJSONEncoder, ScrapyJSONDecoder
from scrapy_jsonrpc.txweb import JsonResource


logger = logging.getLogger(__name__)


class JsonCrawlerResource(JsonResource):

    def __init__(self, crawler):
        super(JsonCrawlerResource, self).__init__()

        self.crawler = crawler
        self.json_encoder = ScrapyJSONEncoder(crawler=crawler)
        self.json_decoder = ScrapyJSONDecoder(crawler=crawler)

    def getChildWithDefault(self, path, request):
        path = path.decode()
        return super(JsonCrawlerResource, self).getChildWithDefault(path, request)


class JsonRpcCrawlerResource(JsonCrawlerResource):

    def __init__(self, crawler, target=None):
        super(JsonRpcCrawlerResource, self).__init__(crawler)

        self._target = target or crawler

    def render_GET(self, request):
        return self.get_target()

    def render_POST(self, request):
        request_content = request.content.getvalue()
        target = self.get_target()
        return jsonrpc_server_call(target, request_content, self.json_decoder)

    def getChild(self, name, request):
        target = self.get_target()
        try:
            newtarget = getattr(target, name)
            return JsonRpcCrawlerResource(self.crawler, newtarget)
        except AttributeError:
            return resource.ErrorPage(404, "No Such Resource", "No such child resource.")

    def get_target(self):
        return self._target


class JsonCrawlerRootResource(JsonCrawlerResource):

    def render_GET(self, request):
        return {'resources': list(map(six.u, self.children))}

    def getChild(self, name, request):
        if name == '':
            return self
        return JsonResource.getChild(self, name, request)


class WebService(server.Site, object):

    def __init__(self, crawler):
        if not crawler.settings.getbool('JSONRPC_ENABLED'):
            raise NotConfigured

        logfile = crawler.settings['JSONRPC_LOGFILE']
        port_range = crawler.settings.getlist('JSONRPC_PORT', [6023, 6073])

        self.crawler = crawler
        self.noisy = False
        self.portrange = [int(x) for x in port_range]
        self.host = crawler.settings.get('JSONRPC_HOST', '127.0.0.1')

        root = JsonCrawlerRootResource(crawler)
        root.putChild('crawler', JsonRpcCrawlerResource(self.crawler))

        super(WebService, self).__init__(root, logPath=logfile)

        crawler.signals.connect(self.start_listening, signals.engine_started)
        crawler.signals.connect(self.stop_listening, signals.engine_stopped)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def start_listening(self):
        self.port = listen_tcp(self.portrange, self.host, self)

        logger.debug(
            'Web service listening on {host.host:s}:{host.port:d}'.format(
                host=self.port.getHost()))

    def stop_listening(self):
        self.port.stopListening()
