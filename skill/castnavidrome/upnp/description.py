"""Generation of the UPnP device description and service description XML."""

import xml.sax.saxutils as saxutils

from .constants import (
    AVTRANSPORT_SERVICE_ID,
    AVTRANSPORT_SERVICE_TYPE,
    CONNECTIONMANAGER_SERVICE_ID,
    CONNECTIONMANAGER_SERVICE_TYPE,
    MANUFACTURER,
    MEDIA_RENDERER_DEVICE_TYPE,
    MODEL_DESCRIPTION,
    MODEL_NAME,
    RENDERINGCONTROL_SERVICE_ID,
    RENDERINGCONTROL_SERVICE_TYPE,
)
from .soap import ACTION_ARGUMENTS

SERVICES = {
    'AVTransport': {
        'serviceType': AVTRANSPORT_SERVICE_TYPE,
        'serviceId': AVTRANSPORT_SERVICE_ID,
    },
    'RenderingControl': {
        'serviceType': RENDERINGCONTROL_SERVICE_TYPE,
        'serviceId': RENDERINGCONTROL_SERVICE_ID,
    },
    'ConnectionManager': {
        'serviceType': CONNECTIONMANAGER_SERVICE_TYPE,
        'serviceId': CONNECTIONMANAGER_SERVICE_ID,
    },
}

AVTRANSPORT_ACTIONS = [
    ('Play', [('InstanceID', 'in'), ('Speed', 'in')]),
    ('Pause', [('InstanceID', 'in')]),
    ('Stop', [('InstanceID', 'in')]),
    ('SetAVTransportURI', [('InstanceID', 'in'), ('CurrentURI', 'in'), ('CurrentURIMetaData', 'in')]),
    ('SetNextAVTransportURI', [('InstanceID', 'in'), ('NextURI', 'in'), ('NextURIMetaData', 'in')]),
    ('GetMediaInfo', [('InstanceID', 'in'), ('NrTracks', 'out'), ('MediaDuration', 'out'),
                      ('CurrentURI', 'out'), ('CurrentURIMetaData', 'out'), ('NextURI', 'out'),
                      ('NextURIMetaData', 'out'), ('PlayMedium', 'out'), ('RecordMedium', 'out'),
                      ('WriteMedium', 'out')]),
    ('GetTransportInfo', [('InstanceID', 'in'), ('CurrentTransportState', 'out'),
                          ('CurrentTransportStatus', 'out'), ('CurrentSpeed', 'out')]),
    ('GetPositionInfo', [('InstanceID', 'in'), ('Track', 'out'), ('TrackDuration', 'out'),
                         ('TrackMetaData', 'out'), ('TrackURI', 'out'), ('RelTime', 'out'),
                         ('AbsTime', 'out'), ('RelCount', 'out'), ('AbsCount', 'out')]),
    ('GetDeviceCapabilities', [('InstanceID', 'in'), ('PlayMedia', 'out'), ('RecMedia', 'out'),
                                ('RecQualityModes', 'out')]),
    ('GetCurrentTransportActions', [('InstanceID', 'in'), ('Actions', 'out')]),
    ('GetTransportSettings', [('InstanceID', 'in'), ('PlayMode', 'out'), ('RecQualityMode', 'out')]),
    ('SetPlayMode', [('InstanceID', 'in'), ('NewPlayMode', 'in')]),
    ('Seek', [('InstanceID', 'in'), ('Unit', 'in'), ('Target', 'in')]),
    ('Next', [('InstanceID', 'in')]),
    ('Previous', [('InstanceID', 'in')]),
]

RENDERINGCONTROL_ACTIONS = [
    ('GetVolume', [('InstanceID', 'in'), ('Channel', 'in'), ('CurrentVolume', 'out')]),
    ('SetVolume', [('InstanceID', 'in'), ('Channel', 'in'), ('DesiredVolume', 'in')]),
    ('GetMute', [('InstanceID', 'in'), ('Channel', 'in'), ('CurrentMute', 'out')]),
    ('SetMute', [('InstanceID', 'in'), ('Channel', 'in'), ('DesiredMute', 'in')]),
    ('GetVolumeDB', [('InstanceID', 'in'), ('Channel', 'in'), ('CurrentVolume', 'out')]),
    ('SetVolumeDB', [('InstanceID', 'in'), ('Channel', 'in'), ('DesiredVolume', 'in')]),
    ('GetVolumeRange', [('InstanceID', 'in'), ('Channel', 'in'), ('MinValue', 'out'), ('MaxValue', 'out')]),
]

CONNECTIONMANAGER_ACTIONS = [
    ('GetProtocolInfo', [('Source', 'out'), ('SourceProtocolInfo', 'out'), ('SinkProtocolInfo', 'out')]),
    ('GetCurrentConnectionIDs', [('ConnectionManager', 'out'), ('ConnectionIDs', 'out')]),
    ('GetCurrentConnectionInfo', [('ConnectionID', 'in'), ('RcsID', 'out'), ('AVTransportID', 'out'),
                                  ('ProtocolInfo', 'out'), ('PeerConnectionManager', 'out'),
                                  ('PeerConnectionID', 'out'), ('Direction', 'out'), ('Status', 'out')]),
    ('PrepareForConnection', [('RemoteProtocolInfo', 'in'), ('PeerConnectionManager', 'in'),
                              ('PeerConnectionID', 'in'), ('Direction', 'in'), ('ConnectionID', 'out'),
                              ('AVTransportID', 'out'), ('Result', 'out')]),
    ('ConnectionComplete', [('ConnectionID', 'in'), ('Result', 'out')]),
]

SERVICE_ACTIONS = {
    'AVTransport': AVTRANSPORT_ACTIONS,
    'RenderingControl': RENDERINGCONTROL_ACTIONS,
    'ConnectionManager': CONNECTIONMANAGER_ACTIONS,
}

EXTRA_STATE_VARIABLES = {
    'AVTransport': [
        ('LastChange', 'string', True),
        ('TransportState', 'string', True),
        ('TransportStatus', 'string', True),
        ('TransportPlaySpeed', 'string', True),
        ('CurrentPlayMode', 'string', True),
        ('CurrentTransportActions', 'string', True),
        ('CurrentTrackMetaData', 'string', True),
        ('CurrentTrackURI', 'uri', True),
        ('CurrentTrackDuration', 'string', True),
        ('CurrentTrackNumber', 'ui4', True),
        ('CurrentMediaDuration', 'string', True),
        ('NrTracks', 'ui4', True),
        ('RelativeTimePosition', 'string', True),
        ('AbsoluteTimePosition', 'string', True),
        ('AVTransportURI', 'uri', True),
        ('AVTransportURIMetaData', 'string', True),
        ('NextAVTransportURI', 'uri', True),
        ('NextAVTransportURIMetaData', 'string', True),
        ('PlaybackStorageMedium', 'string', True),
        ('RecordStorageMedium', 'string', True),
        ('PossiblePlaybackStorageMedia', 'string', True),
        ('PossibleRecordStorageMedia', 'string', True),
        ('RecordMedium', 'string', True),
        ('CurrentRecordQualityMode', 'string', True),
        ('PossibleRecordQualityModes', 'string', True),
    ],
    'RenderingControl': [
        ('Volume', 'ui2', True),
        ('Mute', 'boolean', True),
    ],
    'ConnectionManager': [
        ('ProtocolInfo', 'string', True),
        ('SourceProtocolInfo', 'string', True),
        ('SinkProtocolInfo', 'string', True),
        ('CurrentConnectionIDs', 'string', True),
    ],
}


def description_path(udid: str) -> str:
    return f'/description/{udid}.xml'


def scpd_path(service_key: str, udid: str) -> str:
    return f'/scpd/{service_key}/{udid}.xml'


def control_path(service_key: str, udid: str) -> str:
    return f'/control/{service_key}/{udid}'


def event_path(service_key: str, udid: str) -> str:
    return f'/event/{service_key}/{udid}'


def build_device_description(udid: str,
                             friendly_name: str,
                             serial_number: str = '',
                             presentation_url: str = '/',
                             manufacturer_url: str = '',
                             model_url: str = '') -> str:
    """Build the device description document of a media renderer."""

    services = []
    for service_key, service in SERVICES.items():
        services.append(
            '      <service>\n'
            f'        <serviceType>{service["serviceType"]}</serviceType>\n'
            f'        <serviceId>{service["serviceId"]}</serviceId>\n'
            f'        <SCPDURL>{scpd_path(service_key, udid)}</SCPDURL>\n'
            f'        <controlURL>{control_path(service_key, udid)}</controlURL>\n'
            f'        <eventSubURL>{event_path(service_key, udid)}</eventSubURL>\n'
            '      </service>'
        )

    return '\n'.join([
        '<?xml version="1.0"?>',
        '<root xmlns="urn:schemas-upnp-org:device-1-0" xmlns:dlna="urn:schemas-dlna-org:device-1-0">',
        '  <specVersion>',
        '    <major>1</major>',
        '    <minor>1</minor>',
        '  </specVersion>',
        '  <device>',
        f'    <deviceType>{MEDIA_RENDERER_DEVICE_TYPE}</deviceType>',
        f'    <friendlyName>{saxutils.escape(friendly_name)}</friendlyName>',
        f'    <manufacturer>{MANUFACTURER}</manufacturer>',
        f'    <manufacturerURL>{saxutils.escape(manufacturer_url)}</manufacturerURL>',
        f'    <modelDescription>{MODEL_DESCRIPTION}</modelDescription>',
        f'    <modelName>{MODEL_NAME}</modelName>',
        '    <modelNumber>1</modelNumber>',
        f'    <modelURL>{saxutils.escape(model_url)}</modelURL>',
        f'    <serialNumber>{saxutils.escape(serial_number or udid)}</serialNumber>',
        f'    <UDN>uuid:{saxutils.escape(udid)}</UDN>',
        '    <UPC>000000000000</UPC>',
        '    <dlna:docType>',
        '      <X_DLNADOC>DMS-1.50</X_DLNADOC>',
        '      <X_DLNACAP>',
        '        <protocolInfo>',
        '          http-get:*:audio/mpeg:*,',
        '          http-get:*:audio/mp4:*,',
        '          http-get:*:audio/L16:*,',
        '          http-get:*:image/jpeg:*,',
        '          http-get:*:image/png:*',
        '        </protocolInfo>',
        '      </X_DLNACAP>',
        '    </dlna:docType>',
        '    <iconList>',
        '      <icon>',
        '        <mimetype>image/png</mimetype>',
        '        <width>48</width>',
        '        <height>48</height>',
        '        <depth>24</depth>',
        '        <url>/icon.png</url>',
        '      </icon>',
        '    </iconList>',
        f'    <presentationURL>{saxutils.escape(presentation_url)}</presentationURL>',
        '    <serviceList>',
        *services,
        '    </serviceList>',
        '  </device>',
        '</root>',
        '',
    ])


def build_scpd(service_key: str) -> str:
    """Build the service description document of a service."""

    actions = SERVICE_ACTIONS.get(service_key, [])

    action_lines = []
    state_variables = {}

    for action_name, arguments in actions:
        argument_lines = []
        for argument_name, direction in arguments:
            data_type = ACTION_ARGUMENTS.get(argument_name, 'string')
            state_variable = f'A_ARG_TYPE_{argument_name}'
            state_variables[argument_name] = (state_variable, data_type)
            argument_lines.append(
                '        <argument>\n'
                f'          <name>{argument_name}</name>\n'
                f'          <direction>{direction}</direction>\n'
                f'          <relatedStateVariable>{state_variable}</relatedStateVariable>\n'
                '        </argument>'
            )

        action_lines.append(
            '    <action>\n'
            f'      <name>{action_name}</name>\n'
            '      <argumentList>\n'
            + '\n'.join(argument_lines) + '\n'
            '      </argumentList>\n'
            '    </action>'
        )

    variable_lines = []
    for name, (state_variable, data_type) in sorted(state_variables.items()):
        variable_lines.append(
            '    <stateVariable sendEvents="no">\n'
            f'      <name>{state_variable}</name>\n'
            f'      <dataType>{data_type}</dataType>\n'
            '    </stateVariable>'
        )

    for name, data_type, send_events in EXTRA_STATE_VARIABLES.get(service_key, []):
        variable_lines.append(
            f'    <stateVariable sendEvents="{"yes" if send_events else "no"}">\n'
            f'      <name>{name}</name>\n'
            f'      <dataType>{data_type}</dataType>\n'
            '    </stateVariable>'
        )

    return '\n'.join([
        '<?xml version="1.0"?>',
        '<scpd xmlns="urn:schemas-upnp-org:service-1-0">',
        '  <specVersion>',
        '    <major>1</major>',
        '    <minor>0</minor>',
        '  </specVersion>',
        '  <actionList>',
        *action_lines,
        '  </actionList>',
        '  <serviceStateTable>',
        *variable_lines,
        '  </serviceStateTable>',
        '</scpd>',
        '',
    ])
