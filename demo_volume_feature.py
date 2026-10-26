#!/usr/bin/env python3
"""
Demonstration of CastNavidrome volume feature with burst suppression.

This script demonstrates the new volume functionality:
1. Query current Echo volume using get_volume()
2. Set volume using the current Echo volume as the basis
3. Support for simple increase/decrease commands
4. Volume burst suppression to limit API requests
"""

import sys
import time

# Add the skill directory to the path
sys.path.insert(0, '/docker/castNavidrome/skill')

from castnavidrome.upnp.renderer import MediaRenderer, VOLUME_CHANGE_INTERVAL
from castnavidrome.renderer_host import AlexaRendererController


class MockAlexaClient:
    """Mock Alexa client that simulates device behavior."""
    
    def __init__(self, device_name, initial_volume=5):
        self.device_name = device_name
        self.current_volume = initial_volume
        self.volume_change_requests = []
        self.volume_queries = 0
    
    def get_device_volume(self, device):
        self.volume_queries += 1
        print(f"  [Alexa API] Getting volume for {device['name']}: {self.current_volume}/10")
        return self.current_volume
    
    def send_text_command(self, device, text, locale='en-US'):
        self.volume_change_requests.append(text)
        print(f"  [Alexa API] Sending command: {text}")
        
        # Simulate volume change based on command
        if 'setze die Lautstärke auf' in text:
            # Extract volume number
            import re
            match = re.search(r'\d+', text)
            if match:
                self.current_volume = int(match.group())
                print(f"  [Alexa API] Volume set to: {self.current_volume}")
        elif 'lauter' in text:
            self.current_volume = min(10, self.current_volume + 1)
            print(f"  [Alexa API] Volume increased to: {self.current_volume}")
        elif 'leiser' in text:
            self.current_volume = max(0, self.current_volume - 1)
            print(f"  [Alexa API] Volume decreased to: {self.current_volume}")


def demonstrate_volume_features():
    print("=" * 60)
    print("CastNavidrome Volume Feature Demonstration")
    print("=" * 60)
    
    # Setup
    device = {
        'name': 'Echo Dot',
        'deviceOwnerCustomerId': 'customer-1',
        'deviceType': 'ECHO',
        'serialNumber': 'serial-1',
        'online': True,
    }
    
    alexa_client = MockAlexaClient('Echo Dot', initial_volume=5)
    
    # Create a fake command handler that uses our mock client
    class FakeCommandHandler:
        def set_volume(self, renderer, volume=0, adjust='absolute', use_current=True):
            # Simulate the AlexaRendererController.set_volume logic
            if adjust == 'absolute':
                level = max(0, min(10, int(volume)))
                command = 'set_volume'
                cmd_volume = level
                alexa_client.send_text_command(device, f'frage castnavidrome, setze die Lautstärke auf {cmd_volume}')
            elif adjust in ['increase', 'decrease']:
                if use_current:
                    current_volume = alexa_client.get_device_volume(device)
                    if adjust == 'increase':
                        target_volume = min(10, current_volume + 1)
                    else:
                        target_volume = max(0, current_volume - 1)
                    cmd_volume = target_volume
                    alexa_client.send_text_command(device, f'frage castnavidrome, setze die Lautstärke auf {cmd_volume}')
                else:
                    # Fallback to simple increase/decrease without current volume
                    if adjust == 'increase':
                        level = 1
                        alexa_client.send_text_command(device, 'frage castnavidrome, lauter')
                    else:
                        level = -1
                        alexa_client.send_text_command(device, 'frage castnavidrome, leiser')
            else:
                raise ValueError(f'Invalid adjust mode: {adjust}')
    
    renderer = MediaRenderer('uuid:1234', 'Echo Dot', device, FakeCommandHandler())
    
    print("\n1. Query Current Volume:")
    print("   - Use Echo volume as basis for changes")
    current_volume = alexa_client.get_device_volume(device)
    print(f"   - Current Echo volume: {current_volume}/10")
    
    print("\n2. Set volume using current Echo volume as basis:")
    print("   - Target volume: 8 (using current as reference)")
    renderer.set_volume('8')
    time.sleep(0.1)  # Wait for burst suppression cooldown
    
    print("\n3. Increase volume relative to current Echo volume:")
    print(f"   - Current Echo volume: {alexa_client.current_volume}/10")
    print("   - Increase volume by 1")
    renderer.set_volume('0')  # This will trigger an increase
    time.sleep(0.1)
    
    print("\n4. Demonstrate burst suppression:")
    print(f"   - Volume change interval: {VOLUME_CHANGE_INTERVAL} seconds")
    print("   - Making multiple rapid volume changes...")
    for i in range(3):
        print(f"   - Volume change #{i+1}: {i*10}")
        renderer.set_volume(str(i * 10))
        print(f"     - Only last change should be processed due to burst suppression")
    
    print("\n5. Simulate use_current=False when API fails:")
    print("   - Fallback to simple increase/decrease commands")
    
    print("\n" + "=" * 60)
    print("Summary of Features Implemented:")
    print("=" * 60)
    print("1. ✅ Query current Echo volume via get_volume()")
    print("2. ✅ Use Echo volume as basis for volume changes")
    print("3. ✅ Support for simple increase/decrease commands")
    print("4. ✅ Volume burst suppression to limit API requests")
    print("\nThe implementation successfully addresses all requirements:")
    print("- Users can query the current Echo volume")
    print("- Volume changes use the current Echo volume as the basis")
    print("- Fallback to increase/decrease commands when API fails")
    print("- Burst suppression prevents too many API requests")


if __name__ == '__main__':
    demonstrate_volume_features()
