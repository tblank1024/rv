"""
Test module for the Kasa Power Strip HS300 controller.

This module provides comprehensive unit tests for the KasaPowerStrip class,
including tests for communication, outlet control, and error handling.
"""

import json
import pytest
import socket
import struct
from unittest.mock import Mock, patch, MagicMock
from kasa_ctrl import KasaPowerStrip, KasaProtocolError


class TestKasaPowerStrip:
    """Test suite for KasaPowerStrip class."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.host = "192.168.1.100"
        self.port = 9999
        self.timeout = 5
        self.power_strip = KasaPowerStrip(self.host, self.port, self.timeout)
    
    def test_init(self):
        """Test KasaPowerStrip initialization."""
        assert self.power_strip.host == self.host
        assert self.power_strip.port == self.port
        assert self.power_strip.timeout == self.timeout
        assert self.power_strip.num_outlets == 6
    
    def test_init_with_defaults(self):
        """Test KasaPowerStrip initialization with default values."""
        power_strip = KasaPowerStrip("192.168.1.50")
        assert power_strip.host == "192.168.1.50"
        assert power_strip.port == 9999
        assert power_strip.timeout == 5
        assert power_strip.num_outlets == 6
    
    def test_encrypt_decrypt_round_trip(self):
        """Test that encryption and decryption work correctly together."""
        test_data = '{"system":{"get_sysinfo":{}}}'
        encrypted = self.power_strip._encrypt(test_data)
        
        # Create mock decryption data (length + encrypted data)
        decrypted = self.power_strip._decrypt(encrypted)
        assert decrypted == test_data
    
    def test_encrypt_empty_string(self):
        """Test encryption of empty string."""
        encrypted = self.power_strip._encrypt("")
        assert len(encrypted) == 4  # Only length header
        assert struct.unpack('>I', encrypted[:4])[0] == 0
    
    def test_encrypt_simple_string(self):
        """Test encryption of a simple string."""
        test_string = "test"
        encrypted = self.power_strip._encrypt(test_string)
        length = struct.unpack('>I', encrypted[:4])[0]
        assert length == len(test_string)
        assert len(encrypted) == 4 + len(test_string)
    
    def test_decrypt_with_valid_data(self):
        """Test decryption with valid encrypted data."""
        test_string = "hello"
        encrypted = self.power_strip._encrypt(test_string)
        decrypted = self.power_strip._decrypt(encrypted)
        assert decrypted == test_string
    
    @patch('socket.socket')
    def test_send_command_successful(self, mock_socket):
        """Test successful command sending and response receiving."""
        # Setup mock socket
        mock_sock_instance = Mock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance
        
        # Mock response data
        response_dict = {"system": {"get_sysinfo": {"alias": "Test Strip"}}}
        response_json = json.dumps(response_dict)
        encrypted_response = self.power_strip._encrypt(response_json)
        
        mock_sock_instance.recv.side_effect = [
            encrypted_response[:4],  # Length header
            encrypted_response[4:]   # Actual data
        ]
        
        # Test command
        command = {"system": {"get_sysinfo": {}}}
        result = self.power_strip._send_command(command)
        
        # Verify socket operations
        mock_sock_instance.settimeout.assert_called_once_with(self.timeout)
        mock_sock_instance.connect.assert_called_once_with((self.host, self.port))
        mock_sock_instance.send.assert_called_once()
        assert result == response_dict
    
    @patch('socket.socket')
    def test_send_command_connection_error(self, mock_socket):
        """Test command sending with connection error."""
        mock_sock_instance = Mock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance
        mock_sock_instance.connect.side_effect = socket.error("Connection failed")
        
        command = {"system": {"get_sysinfo": {}}}
        
        with pytest.raises(KasaProtocolError, match="Communication error"):
            self.power_strip._send_command(command)
    
    @patch('socket.socket')
    def test_send_command_timeout(self, mock_socket):
        """Test command sending with timeout."""
        mock_sock_instance = Mock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance
        mock_sock_instance.recv.side_effect = socket.timeout("Timeout")
        
        command = {"system": {"get_sysinfo": {}}}
        
        with pytest.raises(KasaProtocolError, match="Communication error"):
            self.power_strip._send_command(command)
    
    @patch('socket.socket')
    def test_send_command_invalid_response_length(self, mock_socket):
        """Test command sending with invalid response length."""
        mock_sock_instance = Mock()
        mock_socket.return_value.__enter__.return_value = mock_sock_instance
        mock_sock_instance.recv.return_value = b"123"  # Less than 4 bytes
        
        command = {"system": {"get_sysinfo": {}}}
        
        with pytest.raises(KasaProtocolError, match="Failed to receive response length"):
            self.power_strip._send_command(command)
    
    @patch.object(KasaPowerStrip, '_send_command')
    def test_get_system_info(self, mock_send_command):
        """Test getting system information."""
        expected_response = {"system": {"get_sysinfo": {"alias": "Test Strip"}}}
        mock_send_command.return_value = expected_response
        
        result = self.power_strip.get_system_info()
        
        expected_command = {"system": {"get_sysinfo": {}}}
        mock_send_command.assert_called_once_with(expected_command)
        assert result == expected_response
    
    @patch.object(KasaPowerStrip, '_send_command')
    def test_turn_on_outlet_valid_id(self, mock_send_command):
        """Test turning on an outlet with valid ID."""
        outlet_id = 2
        expected_response = {"system": {"set_relay_state": {"err_code": 0}}}
        mock_send_command.return_value = expected_response
        
        result = self.power_strip.turn_on_outlet(outlet_id)
        
        expected_command = {
            "context": {"child_ids": ["plug_02"]},
            "system": {"set_relay_state": {"state": 1}}
        }
        mock_send_command.assert_called_once_with(expected_command)
        assert result == expected_response
    
    def test_turn_on_outlet_invalid_id_negative(self):
        """Test turning on outlet with negative ID."""
        with pytest.raises(ValueError, match="Outlet ID must be between 0 and 5"):
            self.power_strip.turn_on_outlet(-1)
    
    def test_turn_on_outlet_invalid_id_too_high(self):
        """Test turning on outlet with ID too high."""
        with pytest.raises(ValueError, match="Outlet ID must be between 0 and 5"):
            self.power_strip.turn_on_outlet(6)
    
    @patch.object(KasaPowerStrip, '_send_command')
    def test_turn_off_outlet_valid_id(self, mock_send_command):
        """Test turning off an outlet with valid ID."""
        outlet_id = 4
        expected_response = {"system": {"set_relay_state": {"err_code": 0}}}
        mock_send_command.return_value = expected_response
        
        result = self.power_strip.turn_off_outlet(outlet_id)
        
        expected_command = {
            "context": {"child_ids": ["plug_04"]},
            "system": {"set_relay_state": {"state": 0}}
        }
        mock_send_command.assert_called_once_with(expected_command)
        assert result == expected_response
    
    def test_turn_off_outlet_invalid_id(self):
        """Test turning off outlet with invalid ID."""
        with pytest.raises(ValueError, match="Outlet ID must be between 0 and 5"):
            self.power_strip.turn_off_outlet(10)
    
    @patch.object(KasaPowerStrip, 'get_outlet_status')
    @patch.object(KasaPowerStrip, 'turn_off_outlet')
    @patch.object(KasaPowerStrip, 'turn_on_outlet')
    def test_toggle_outlet_from_on_to_off(self, mock_turn_on, mock_turn_off, mock_get_status):
        """Test toggling outlet from on to off."""
        outlet_id = 1
        mock_get_status.return_value = {"relay_state": 1}  # Currently on
        mock_turn_off.return_value = {"success": True}
        
        result = self.power_strip.toggle_outlet(outlet_id)
        
        mock_get_status.assert_called_once_with(outlet_id)
        mock_turn_off.assert_called_once_with(outlet_id)
        mock_turn_on.assert_not_called()
        assert result == {"success": True}
    
    @patch.object(KasaPowerStrip, 'get_outlet_status')
    @patch.object(KasaPowerStrip, 'turn_off_outlet')
    @patch.object(KasaPowerStrip, 'turn_on_outlet')
    def test_toggle_outlet_from_off_to_on(self, mock_turn_on, mock_turn_off, mock_get_status):
        """Test toggling outlet from off to on."""
        outlet_id = 3
        mock_get_status.return_value = {"relay_state": 0}  # Currently off
        mock_turn_on.return_value = {"success": True}
        
        result = self.power_strip.toggle_outlet(outlet_id)
        
        mock_get_status.assert_called_once_with(outlet_id)
        mock_turn_on.assert_called_once_with(outlet_id)
        mock_turn_off.assert_not_called()
        assert result == {"success": True}
    
    @patch.object(KasaPowerStrip, 'get_system_info')
    def test_get_outlet_status_valid_id(self, mock_get_system_info):
        """Test getting outlet status with valid ID."""
        outlet_id = 2
        mock_system_info = {
            "system": {
                "get_sysinfo": {
                    "children": [
                        {"id": "plug_00", "alias": "Outlet 0", "state": 1},
                        {"id": "plug_01", "alias": "Outlet 1", "state": 0},
                        {"id": "plug_02", "alias": "Outlet 2", "state": 1},
                    ]
                }
            }
        }
        mock_get_system_info.return_value = mock_system_info
        
        result = self.power_strip.get_outlet_status(outlet_id)
        
        expected_result = {"id": "plug_02", "alias": "Outlet 2", "state": 1}
        assert result == expected_result
    
    @patch.object(KasaPowerStrip, 'get_system_info')
    def test_get_outlet_status_not_found(self, mock_get_system_info):
        """Test getting outlet status when outlet not found."""
        outlet_id = 5
        mock_system_info = {
            "system": {
                "get_sysinfo": {
                    "children": [
                        {"id": "plug_00", "alias": "Outlet 0", "state": 1},
                        {"id": "plug_01", "alias": "Outlet 1", "state": 0},
                    ]
                }
            }
        }
        mock_get_system_info.return_value = mock_system_info
        
        with pytest.raises(KasaProtocolError, match="Outlet 5 not found in system info"):
            self.power_strip.get_outlet_status(outlet_id)
    
    def test_get_outlet_status_invalid_id(self):
        """Test getting outlet status with invalid ID."""
        with pytest.raises(ValueError, match="Outlet ID must be between 0 and 5"):
            self.power_strip.get_outlet_status(7)
    
    @patch.object(KasaPowerStrip, 'get_system_info')
    def test_get_all_outlet_status(self, mock_get_system_info):
        """Test getting status of all outlets."""
        mock_children = [
            {"id": "plug_00", "alias": "Outlet 0", "state": 1},
            {"id": "plug_01", "alias": "Outlet 1", "state": 0},
            {"id": "plug_02", "alias": "Outlet 2", "state": 1},
        ]
        mock_system_info = {
            "system": {"get_sysinfo": {"children": mock_children}}
        }
        mock_get_system_info.return_value = mock_system_info
        
        result = self.power_strip.get_all_outlet_status()
        
        assert result == mock_children
    
    @patch.object(KasaPowerStrip, 'turn_on_outlet')
    def test_turn_on_all_outlets_success(self, mock_turn_on):
        """Test turning on all outlets successfully."""
        mock_turn_on.return_value = {"success": True}
        
        results = self.power_strip.turn_on_all_outlets()
        
        assert len(results) == 6
        assert mock_turn_on.call_count == 6
        
        for i, result in enumerate(results):
            assert result["outlet_id"] == i
            assert result["success"] is True
            assert result["result"] == {"success": True}
    
    @patch.object(KasaPowerStrip, 'turn_on_outlet')
    def test_turn_on_all_outlets_partial_failure(self, mock_turn_on):
        """Test turning on all outlets with some failures."""
        def side_effect(outlet_id):
            if outlet_id == 2:
                raise KasaProtocolError("Communication error")
            return {"success": True}
        
        mock_turn_on.side_effect = side_effect
        
        results = self.power_strip.turn_on_all_outlets()
        
        assert len(results) == 6
        assert mock_turn_on.call_count == 6
        
        # Check successful outlets
        for i in [0, 1, 3, 4, 5]:
            assert results[i]["outlet_id"] == i
            assert results[i]["success"] is True
        
        # Check failed outlet
        assert results[2]["outlet_id"] == 2
        assert results[2]["success"] is False
        assert "Communication error" in results[2]["error"]
    
    @patch.object(KasaPowerStrip, 'turn_off_outlet')
    def test_turn_off_all_outlets_success(self, mock_turn_off):
        """Test turning off all outlets successfully."""
        mock_turn_off.return_value = {"success": True}
        
        results = self.power_strip.turn_off_all_outlets()
        
        assert len(results) == 6
        assert mock_turn_off.call_count == 6
        
        for i, result in enumerate(results):
            assert result["outlet_id"] == i
            assert result["success"] is True
            assert result["result"] == {"success": True}
    
    @patch.object(KasaPowerStrip, '_send_command')
    def test_get_power_consumption_valid_id(self, mock_send_command):
        """Test getting power consumption for valid outlet ID."""
        outlet_id = 1
        expected_response = {
            "emeter": {
                "get_realtime": {
                    "voltage_mv": 120000,
                    "current_ma": 150,
                    "power_mw": 18000,
                    "total_wh": 1500
                }
            }
        }
        mock_send_command.return_value = expected_response
        
        result = self.power_strip.get_power_consumption(outlet_id)
        
        expected_command = {
            "context": {"child_ids": ["plug_01"]},
            "emeter": {"get_realtime": {}}
        }
        mock_send_command.assert_called_once_with(expected_command)
        assert result == expected_response
    
    def test_get_power_consumption_invalid_id(self):
        """Test getting power consumption with invalid outlet ID."""
        with pytest.raises(ValueError, match="Outlet ID must be between 0 and 5"):
            self.power_strip.get_power_consumption(-1)


class TestKasaProtocolError:
    """Test suite for KasaProtocolError exception."""
    
    def test_kasaprotocol_error_creation(self):
        """Test creating KasaProtocolError with message."""
        message = "Test error message"
        error = KasaProtocolError(message)
        assert str(error) == message
    
    def test_kasaprotocol_error_inheritance(self):
        """Test that KasaProtocolError inherits from Exception."""
        error = KasaProtocolError("test")
        assert isinstance(error, Exception)


class TestIntegration:
    """Integration tests for realistic scenarios."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.power_strip = KasaPowerStrip("192.168.1.100")
    
    @patch.object(KasaPowerStrip, '_send_command')
    def test_complete_outlet_control_workflow(self, mock_send_command):
        """Test a complete workflow of outlet control operations."""
        # Mock system info response
        system_info_response = {
            "system": {
                "get_sysinfo": {
                    "children": [
                        {"id": "plug_00", "alias": "TV", "state": 0},
                        {"id": "plug_01", "alias": "Lamp", "state": 1},
                    ]
                }
            }
        }
        
        # Mock command responses
        command_response = {"system": {"set_relay_state": {"err_code": 0}}}
        
        mock_send_command.side_effect = [
            system_info_response,  # get_system_info
            command_response,      # turn_on_outlet
            system_info_response,  # get_outlet_status (for toggle)
            command_response,      # turn_off_outlet (from toggle)
        ]
        
        # Test workflow
        # 1. Get system info
        info = self.power_strip.get_system_info()
        assert "children" in info["system"]["get_sysinfo"]
        
        # 2. Turn on outlet 0
        result = self.power_strip.turn_on_outlet(0)
        assert result == command_response
        
        # 3. Toggle outlet 1 (should turn off since it's currently on)
        toggle_result = self.power_strip.toggle_outlet(1)
        assert toggle_result == command_response
        
        # Verify all expected calls were made
        assert mock_send_command.call_count == 4


if __name__ == "__main__":
    # Run tests when executed directly
    pytest.main([__file__, "-v"])