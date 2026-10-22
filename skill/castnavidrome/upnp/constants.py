"""Constants and service descriptions of the UPnP media renderer."""

MEDIA_RENDERER_DEVICE_TYPE = 'urn:schemas-upnp-org:device:MediaRenderer:1'
ROOT_DEVICE_TYPE = 'urn:schemas-upnp-org:device:MediaRenderer:1'

AVTRANSPORT_SERVICE_TYPE = 'urn:schemas-upnp-org:service:AVTransport:1'
RENDERINGCONTROL_SERVICE_TYPE = 'urn:schemas-upnp-org:service:RenderingControl:1'
CONNECTIONMANAGER_SERVICE_TYPE = 'urn:schemas-upnp-org:service:ConnectionManager:1'

AVTRANSPORT_SERVICE_ID = 'urn:upnp-org:serviceId:AVTransport'
RENDERINGCONTROL_SERVICE_ID = 'urn:upnp-org:serviceId:RenderingControl'
CONNECTIONMANAGER_SERVICE_ID = 'urn:upnp-org:serviceId:ConnectionManager'

AVTRANSPORT_EVENT_TYPE = 'urn:schemas-upnp-org:metadata-1-0/AVT/'
RENDERINGCONTROL_EVENT_TYPE = 'urn:schemas-upnp-org:metadata-1-0/RCS/'

MANUFACTURER = 'castNavidrome'
MODEL_NAME = 'Alexa Media Renderer'
MODEL_DESCRIPTION = 'Exposes an Alexa device as a UPnP media renderer for Navidrome'

# The volume of an Alexa device is controlled in steps from 0 to 10.
ALEXA_VOLUME_MIN = 0
ALEXA_VOLUME_MAX = 10
# The UPnP rendering control uses a volume between 0 and 100.
UPNP_VOLUME_MAX = 100
