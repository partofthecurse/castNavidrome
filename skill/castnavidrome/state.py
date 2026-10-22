"""Shared runtime state of the castNavidrome web service.

This module owns one MediaQueue instance PER DEVICE, keyed by the ID of the
Alexa device that sent the request.  Without this, two Echo devices talking
to the same skill would share one queue and trample each other's playback
state: the second device would clear the queue of the first one, so that the
first device stops playing and its next track is never queued.

A device's queue is created lazily, the first time it is requested, so
there is no separate "register a device" step.  Queues of devices that stop
being used are never evicted; for a household scale deployment this is an
acceptable simplification, an idle queue only costs a few empty deques in the
manager subprocess.

Ported from bickns/asknavidrome (MIT), see CREDITS.md.  The lazy start of
the manager, the fallback for requests without a device and the usage of the
renderer registry are our own local changes.
"""

import logging
from multiprocessing.managers import BaseManager

import castnavidrome.media_queue as queue


logger = logging.getLogger(__name__)

DEFAULT_DEVICE_ID = 'default'
"""The device that is used for requests without a device context"""

_manager = None
"""The manager that shares the play queues between the processes"""

_queues_by_device = {}
"""device_id -> MediaQueue instance"""

_background_by_device = {}
"""device_id -> Process instance, or None"""


def get_manager() -> BaseManager:
    """Get the manager that shares the play queues between the processes

    The manager is started with the first request that needs a queue, so
    that importing this module does not start a process.

    :return: The running manager
    :rtype: BaseManager
    """

    global _manager

    if _manager is None:
        BaseManager.register('MediaQueue', queue.MediaQueue)
        _manager = BaseManager()
        _manager.start()
        logger.debug('The media queue manager has been started')

    return _manager


def get_device_id(handler_input) -> str:
    """Get the ID of the device that sent the request

    Every device has its own play queue, so that the devices do not
    interfere with each other.  Some requests, for example the ones from the
    Alexa app, do not have a device context.  They all share a default
    device, so that the playback still works for them.

    :param handler_input: The Amazon Alexa HandlerInput object
    :return: The ID of the device
    :rtype: str
    """

    try:
        device = handler_input.request_envelope.context.system.device
    except AttributeError:
        return DEFAULT_DEVICE_ID

    if device is None or not device.device_id:
        return DEFAULT_DEVICE_ID

    return device.device_id


def get_play_queue(device_id: str):
    """Get the play queue of a device, creating it if it does not exist yet

    Every call returns the same queue for the same device, and a different
    queue for a different device.

    :param str device_id: The ID of the Alexa device
    :return: The play queue of the device
    """

    if device_id not in _queues_by_device:
        _queues_by_device[device_id] = get_manager().MediaQueue()
        logger.debug('Created a new play queue for the device %s', device_id)

    return _queues_by_device[device_id]


def get_known_device_ids() -> list:
    """Get the IDs of all the devices that have a play queue

    :return: A list of the device IDs
    :rtype: list
    """

    return list(_queues_by_device.keys())


def get_background_process(device_id: str):
    """Get the background process of a device

    :param str device_id: The ID of the Alexa device
    :return: The process or None if there is no process running
    """

    return _background_by_device.get(device_id)


def set_background_process(device_id: str, process) -> None:
    """Set the background process of a device

    :param str device_id: The ID of the Alexa device
    :param process: The new process, or None to clear it
    :return: None
    """

    _background_by_device[device_id] = process


def stop_background_process(device_id: str) -> None:
    """Stop the background process of a device

    The process is terminated and joined, so that it cannot add any more
    tracks to the queue of the device.  It is safe to call this if there is
    no process running.

    Every handler that starts a new play list has to call this before it
    starts a new process, so that two processes do not race to populate the
    same queue.

    :param str device_id: The ID of the Alexa device
    :return: None
    """

    process = _background_by_device.get(device_id)

    if process is not None:
        process.terminate()
        process.join()
        _background_by_device[device_id] = None
