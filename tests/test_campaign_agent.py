"""Tests for campaign_agent.py autonomous campaign orchestration."""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import urllib.error

import pytest

from campaign_agent import run_autonomous_campaign, trigger_n8n_webhook


class TestRunAutonomousCampaign:
    """Tests for the main autonomous campaign orchestration function."""

    def test_basic_campaign_with_image_only(self, tmp_path):
        """Test campaign creation with image asset only (no video)."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"fake image data")
        output_dir = tmp_path / "output"
        
        with patch("campaign_agent.run_image_agent") as mock_image, \
             patch("campaign_agent.run_editing_agent") as mock_video:
            
            processed_img = str(tmp_path / "processed.png")
            mock_image.return_value = processed_img
            
            result = run_autonomous_campaign(
                product_name="TestProduct",
                raw_image_path=str(test_image),
                target_platform="TikTok",
                raw_video_path=None,
                webhook_url="",
                output_dir=str(output_dir)
            )
        
        # Verify structure
        assert result["campaign_name"] == "TestProduct"
        assert result["platform"] == "TikTok"
        assert result["assets"]["hero_image"] == processed_img
        assert result["assets"]["promo_video"] is None
        assert result["status"] == "ready"
        assert result["webhook_dispatched"] is False
        
        # Verify content schedule
        assert len(result["content_schedule"]) == 3
        assert "TestProduct" in result["content_schedule"][0]["topic"]
        
        # Verify n8n payload structure
        assert result["n8n_payload"]["name"] == "Omnichannel Auto-Publisher: TestProduct"
        assert len(result["n8n_payload"]["nodes"]) == 2
        assert "Webhook Trigger" in [n["name"] for n in result["n8n_payload"]["nodes"]]
        
        # Video agent should not be called when raw_video_path is None
        mock_video.assert_not_called()

    def test_campaign_with_image_and_video(self, tmp_path):
        """Test campaign creation with both image and video assets."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"fake image")
        test_video = tmp_path / "test.mp4"
        test_video.write_bytes(b"fake video")
        
        with patch("campaign_agent.run_image_agent") as mock_image, \
             patch("campaign_agent.run_editing_agent") as mock_video:
            
            processed_img = str(tmp_path / "processed.png")
            processed_vid = str(tmp_path / "processed.mp4")
            mock_image.return_value = processed_img
            mock_video.return_value = processed_vid
            
            result = run_autonomous_campaign(
                product_name="FullProduct",
                raw_image_path=str(test_image),
                target_platform="YouTube",
                raw_video_path=str(test_video),
                webhook_url="",
                output_dir=str(tmp_path)
            )
        
        assert result["assets"]["hero_image"] == processed_img
        assert result["assets"]["promo_video"] == processed_vid
        assert result["status"] == "ready"
        
        # Both agents should be called
        mock_image.assert_called_once()
        mock_video.assert_called_once()
        
        # Video prompt should reference product name
        video_call_args = mock_video.call_args
        assert "FullProduct" in video_call_args[0][0]

    def test_video_agent_failure_fallback(self, tmp_path):
        """Test graceful fallback when video editing agent fails."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"fake image")
        test_video = tmp_path / "test.mp4"
        test_video.write_bytes(b"fake video")
        
        with patch("campaign_agent.run_image_agent") as mock_image, \
             patch("campaign_agent.run_editing_agent") as mock_video:
            
            processed_img = str(tmp_path / "processed.png")
            mock_image.return_value = processed_img
            mock_video.side_effect = RuntimeError("Video processing failed")
            
            result = run_autonomous_campaign(
                product_name="Product",
                raw_image_path=str(test_image),
                target_platform="Instagram",
                raw_video_path=str(test_video),
                webhook_url=""
            )
        
        # Should still succeed with image only
        assert result["assets"]["hero_image"] == processed_img
        assert result["assets"]["promo_video"] is None
        assert result["status"] == "ready"  # Still ready because image succeeded

    def test_nonexistent_video_path_ignored(self, tmp_path):
        """Test that nonexistent video path doesn't trigger video agent."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"fake image")
        
        with patch("campaign_agent.run_image_agent") as mock_image, \
             patch("campaign_agent.run_editing_agent") as mock_video:
            
            mock_image.return_value = str(tmp_path / "processed.png")
            
            result = run_autonomous_campaign(
                product_name="Product",
                raw_image_path=str(test_image),
                target_platform="TikTok",
                raw_video_path="/nonexistent/path.mp4",
                webhook_url=""
            )
        
        # Video agent should not be called for nonexistent file
        mock_video.assert_not_called()
        assert result["assets"]["promo_video"] is None

    def test_webhook_dispatch_with_valid_url(self, tmp_path):
        """Test webhook dispatch when valid URL provided."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"fake image")
        
        with patch("campaign_agent.run_image_agent") as mock_image, \
             patch("campaign_agent.trigger_n8n_webhook") as mock_webhook:
            
            mock_image.return_value = str(tmp_path / "processed.png")
            mock_webhook.return_value = True
            
            result = run_autonomous_campaign(
                product_name="Product",
                raw_image_path=str(test_image),
                target_platform="LinkedIn",
                webhook_url="https://webhook.site/test-endpoint"
            )
        
        assert result["webhook_dispatched"] is True
        mock_webhook.assert_called_once()
        
        # Verify webhook was called with n8n payload
        call_args = mock_webhook.call_args
        assert call_args[0][0] == "https://webhook.site/test-endpoint"
        payload = call_args[0][1]
        assert "nodes" in payload
        assert "connections" in payload

    def test_webhook_dispatch_failure_handled_gracefully(self, tmp_path):
        """Test that webhook dispatch failure doesn't crash campaign."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"fake image")
        
        with patch("campaign_agent.run_image_agent") as mock_image, \
             patch("campaign_agent.trigger_n8n_webhook") as mock_webhook:
            
            mock_image.return_value = str(tmp_path / "processed.png")
            mock_webhook.return_value = False  # Webhook failed
            
            result = run_autonomous_campaign(
                product_name="Product",
                raw_image_path=str(test_image),
                target_platform="TikTok",
                webhook_url="https://webhook.site/test"
            )
        
        assert result["webhook_dispatched"] is False
        # Campaign should still be successful
        assert result["status"] == "ready"

    def test_empty_webhook_url_skips_dispatch(self, tmp_path):
        """Test that empty webhook URL doesn't attempt dispatch."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"fake image")
        
        with patch("campaign_agent.run_image_agent") as mock_image, \
             patch("campaign_agent.trigger_n8n_webhook") as mock_webhook:
            
            mock_image.return_value = str(tmp_path / "processed.png")
            
            result = run_autonomous_campaign(
                product_name="Product",
                raw_image_path=str(test_image),
                target_platform="TikTok",
                webhook_url=""
            )
        
        mock_webhook.assert_not_called()
        assert result["webhook_dispatched"] is False

    def test_n8n_payload_structure(self, tmp_path):
        """Test that generated n8n payload has correct structure."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"fake image")
        
        with patch("campaign_agent.run_image_agent") as mock_image:
            mock_image.return_value = "/path/to/processed.png"
            
            result = run_autonomous_campaign(
                product_name="StructureTest",
                raw_image_path=str(test_image),
                target_platform="Instagram",
                webhook_url=""
            )
        
        n8n = result["n8n_payload"]
        
        # Validate top-level structure
        assert "name" in n8n
        assert "nodes" in n8n
        assert "connections" in n8n
        assert "settings" in n8n
        assert "tags" in n8n
        
        # Validate nodes
        assert len(n8n["nodes"]) >= 2
        node_names = [node["name"] for node in n8n["nodes"]]
        assert "Webhook Trigger" in node_names
        assert "Set Campaign Assets" in node_names
        
        # Validate connections
        assert "Webhook Trigger" in n8n["connections"]
        assert len(n8n["connections"]["Webhook Trigger"]["main"]) > 0

    def test_content_schedule_generation(self, tmp_path):
        """Test that content schedule is properly generated."""
        test_image = tmp_path / "test.png"
        test_image.write_bytes(b"fake image")
        
        with patch("campaign_agent.run_image_agent") as mock_image:
            mock_image.return_value = "/processed.png"
            
            result = run_autonomous_campaign(
                product_name="ScheduleTest",
                raw_image_path=str(test_image),
                target_platform="YouTube",
                webhook_url=""
            )
        
        schedule = result["content_schedule"]
        assert len(schedule) == 3
        
        # Verify all schedule items have required fields
        for item in schedule:
            assert "topic" in item
            assert "status" in item
            assert "format" in item
            assert "media_type" in item
            assert "asset_ref" in item
            assert "tags" in item
            assert "ScheduleTest" in item["topic"]


class TestTriggerN8nWebhook:
    """Tests for the n8n webhook dispatch function."""

    def test_valid_https_webhook(self):
        """Test successful webhook dispatch to HTTPS endpoint."""
        payload = {"test": "data"}
        
        with patch("campaign_agent.urllib.request.build_opener") as mock_opener:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_opener.return_value.open.return_value.__enter__.return_value = mock_response
            
            result = trigger_n8n_webhook("https://webhook.site/unique-endpoint", payload)
        
        assert result is True

    def test_webhook_with_201_response(self):
        """Test webhook accepts 201 Created response."""
        with patch("campaign_agent.urllib.request.build_opener") as mock_opener:
            mock_response = MagicMock()
            mock_response.status = 201
            mock_opener.return_value.open.return_value.__enter__.return_value = mock_response
            
            result = trigger_n8n_webhook("https://webhook.site/test", {})
        
        assert result is True

    def test_invalid_scheme_rejected(self):
        """Test that non-HTTP(S) schemes are rejected."""
        with pytest.raises(ValueError, match="must be an absolute HTTP"):
            trigger_n8n_webhook("ftp://example.com/webhook", {})

    def test_relative_url_rejected(self):
        """Test that relative URLs are rejected."""
        with pytest.raises(ValueError, match="must be an absolute HTTP"):
            trigger_n8n_webhook("/webhook/endpoint", {})

    def test_missing_hostname_rejected(self):
        """Test that URL without hostname is rejected."""
        # "https://" gets caught by the netloc check first
        with pytest.raises(ValueError, match="must be an absolute HTTP"):
            trigger_n8n_webhook("https://", {})

    def test_private_ip_rejected(self):
        """Test SSRF protection: private IP addresses rejected."""
        with patch("campaign_agent.socket.getaddrinfo") as mock_getaddr:
            # Mock DNS resolution to private IP
            mock_getaddr.return_value = [
                (None, None, None, None, ("192.168.1.1", 80))
            ]
            
            with pytest.raises(ValueError, match="cannot target a private"):
                trigger_n8n_webhook("https://internal.company.com/webhook", {})

    def test_loopback_ip_rejected(self):
        """Test SSRF protection: loopback addresses rejected."""
        with patch("campaign_agent.socket.getaddrinfo") as mock_getaddr:
            mock_getaddr.return_value = [
                (None, None, None, None, ("127.0.0.1", 80))
            ]
            
            with pytest.raises(ValueError, match="cannot target a private"):
                trigger_n8n_webhook("https://localhost/webhook", {})

    def test_link_local_ip_rejected(self):
        """Test SSRF protection: link-local addresses rejected."""
        with patch("campaign_agent.socket.getaddrinfo") as mock_getaddr:
            mock_getaddr.return_value = [
                (None, None, None, None, ("169.254.1.1", 80))
            ]
            
            with pytest.raises(ValueError, match="cannot target a private"):
                trigger_n8n_webhook("https://autoconf.local/webhook", {})

    def test_unresolvable_hostname(self):
        """Test handling of DNS resolution failure."""
        with patch("campaign_agent.socket.getaddrinfo") as mock_getaddr:
            mock_getaddr.side_effect = socket.gaierror("Name resolution failed")
            
            with pytest.raises(ValueError, match="could not be resolved"):
                trigger_n8n_webhook("https://nonexistent.invalid/webhook", {})

    def test_http_error_returns_false(self):
        """Test that HTTP errors return False rather than raising."""
        with patch("campaign_agent.urllib.request.build_opener") as mock_opener, \
             patch("campaign_agent.socket.getaddrinfo") as mock_getaddr:
            
            mock_getaddr.return_value = [
                (None, None, None, None, ("1.2.3.4", 443))
            ]
            mock_opener.return_value.open.side_effect = urllib.error.HTTPError(
                "https://example.com/webhook", 404, "Not Found", {}, None
            )
            
            result = trigger_n8n_webhook("https://example.com/webhook", {})
        
        assert result is False

    def test_network_timeout_returns_false(self):
        """Test that network timeout returns False."""
        with patch("campaign_agent.urllib.request.build_opener") as mock_opener, \
             patch("campaign_agent.socket.getaddrinfo") as mock_getaddr:
            
            mock_getaddr.return_value = [
                (None, None, None, None, ("1.2.3.4", 443))
            ]
            mock_opener.return_value.open.side_effect = urllib.error.URLError("Timeout")
            
            result = trigger_n8n_webhook("https://slow.example.com/webhook", {})
        
        assert result is False

    def test_redirect_blocked(self):
        """Test that HTTP redirects are blocked (SSRF protection)."""
        with patch("campaign_agent.urllib.request.build_opener") as mock_opener, \
             patch("campaign_agent.socket.getaddrinfo") as mock_getaddr:
            
            mock_getaddr.return_value = [
                (None, None, None, None, ("1.2.3.4", 443))
            ]
            # Redirect handler should raise HTTPError for redirects
            mock_opener.return_value.open.side_effect = urllib.error.HTTPError(
                "https://example.com/webhook", 301, "Moved", {}, None
            )
            
            result = trigger_n8n_webhook("https://example.com/webhook", {})
        
        assert result is False

    def test_payload_json_encoded(self):
        """Test that payload is properly JSON-encoded."""
        payload = {"campaign": "test", "assets": ["img1.png"]}
        
        with patch("campaign_agent.urllib.request.build_opener") as mock_opener, \
             patch("campaign_agent.urllib.request.Request") as mock_request, \
             patch("campaign_agent.socket.getaddrinfo") as mock_getaddr:
            
            mock_getaddr.return_value = [
                (None, None, None, None, ("1.2.3.4", 443))
            ]
            mock_response = MagicMock()
            mock_response.status = 200
            mock_opener.return_value.open.return_value.__enter__.return_value = mock_response
            
            trigger_n8n_webhook("https://webhook.site/test", payload)
            
            # Verify Request was called with JSON-encoded data
            call_args = mock_request.call_args
            assert call_args[1]["data"] == json.dumps(payload).encode("utf-8")
            assert call_args[1]["headers"]["Content-Type"] == "application/json"
