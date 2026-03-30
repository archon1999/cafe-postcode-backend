from rest_framework.renderers import BaseRenderer


class BinaryFileRenderer(BaseRenderer):
    media_type = 'application/octet-stream'
    format = None
    charset = None
    render_style = 'binary'

    def render(self, data, media_type=None, renderer_context=None):
        return data


class SvgRenderer(BaseRenderer):
    media_type = 'image/svg+xml'
    format = 'svg'
    charset = 'utf-8'
    render_style = 'text'

    def render(self, data, media_type=None, renderer_context=None):
        return data
