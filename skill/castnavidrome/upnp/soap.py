"""Parsing of SOAP requests and creation of SOAP responses."""

import logging
import xml.etree.ElementTree as ElementTree

logger = logging.getLogger(__name__)

SOAP_ENVELOPE_NAMESPACE = 'http://schemas.xmlsoap.org/soap/envelope/'
SOAP_ENCODING_NAMESPACE = 'http://schemas.xmlsoap.org/soap/encoding/'

ACTION_ARGUMENTS = {
    'InstanceID': 'ui4',
    'Speed': 'r4',
    'CurrentURI': 'string',
    'CurrentURIMetaData': 'string',
    'NextURI': 'string',
    'NextURIMetaData': 'string',
    'Channel': 'string',
    'DesiredVolume': 'ui2',
    'CurrentVolume': 'ui2',
    'DesiredMute': 'boolean',
    'CurrentMute': 'boolean',
    'Unit': 'string',
    'Target': 'string',
    'NewPlayMode': 'string',
    'ConnectionID': 'i4',
    'AVTransportID': 'i4',
    'ProtocolInfo': 'string',
    'SourceProtocolInfo': 'string',
    'SinkProtocolInfo': 'string',
    'PeerConnectionManager': 'string',
    'PeerConnectionID': 'i4',
    'Direction': 'string',
    'RcsID': 'i4',
    'Status': 'string',
    'Result': 'string',
}


class SoapError(Exception):
    """Raised when a SOAP request cannot be handled."""

    def __init__(self, message: str, error_code: int = 401) -> None:
        super().__init__(message)
        self.error_code = error_code


class SoapRequest:
    """A parsed SOAP action invocation."""

    def __init__(self, service_type: str, action: str, arguments: dict) -> None:
        self.service_type = service_type
        self.action = action
        self.arguments = arguments

    def argument(self, name: str, default: str = '') -> str:
        value = self.arguments.get(name, default)
        return value if isinstance(value, str) else str(value)


def _local_name(tag: str) -> str:
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag


def parse_soap_request(body: bytes) -> SoapRequest:
    """Parse a SOAP request body into a :class:`SoapRequest`."""

    if not body:
        raise SoapError('The SOAP request body is empty.')

    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise SoapError(f'The SOAP request body is not valid XML: {error}') from None

    body_element = root.find(f'{{{SOAP_ENVELOPE_NAMESPACE}}}Body')
    if body_element is None:
        body_element = root.find('Body')

    if body_element is None or len(body_element) == 0:
        raise SoapError('The SOAP request does not contain an action.')

    action_element = list(body_element)[0]
    action = _local_name(action_element.tag)

    service_type = ''
    if action_element.tag.startswith('{'):
        service_type = action_element.tag.split('}', 1)[0][1:]

    arguments = {}
    for argument in action_element:
        arguments[_local_name(argument.tag)] = (argument.text or '').strip()

    return SoapRequest(service_type, action, arguments)


def build_soap_response(service_type: str, action: str, arguments: dict = None) -> bytes:
    """Build a SOAP response for the given action."""

    arguments = arguments or {}

    lines = [
        '<?xml version="1.0"?>',
        f'<s:Envelope xmlns:s="{SOAP_ENVELOPE_NAMESPACE}" s:encodingStyle="{SOAP_ENCODING_NAMESPACE}">',
        '<s:Body>',
        f'<u:{action}Response xmlns:u="{service_type}">',
    ]

    for name, value in arguments.items():
        lines.append(f'<{name}>{_escape(value)}</{name}>')

    lines.extend([
        f'</u:{action}Response>',
        '</s:Body>',
        '</s:Envelope>',
    ])

    return '\n'.join(lines).encode('utf-8')


def build_soap_fault(error_code: int = 401, error_description: str = 'Invalid Action') -> bytes:
    """Build a SOAP fault response."""

    lines = [
        '<?xml version="1.0"?>',
        f'<s:Envelope xmlns:s="{SOAP_ENVELOPE_NAMESPACE}" s:encodingStyle="{SOAP_ENCODING_NAMESPACE}">',
        '<s:Body>',
        '<s:Fault>',
        '<faultcode>s:Client</faultcode>',
        '<faultstring>UPnPError</faultstring>',
        '<detail>',
        '<UPnPError xmlns="urn:schemas-upnp-org:control-1-0">',
        f'<errorCode>{error_code}</errorCode>',
        f'<errorDescription>{_escape(error_description)}</errorDescription>',
        '</UPnPError>',
        '</detail>',
        '</s:Fault>',
        '</s:Body>',
        '</s:Envelope>',
    ]

    return '\n'.join(lines).encode('utf-8')


def _escape(value) -> str:
    text = '' if value is None else str(value)
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;'))
