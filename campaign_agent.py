import os
import json

import urllib.request
from urllib.parse import urlparse
import ipaddress
import socket
from typing import Optional
from image_agent import run_image_agent
from orchestrator import run_editing_agent


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_301(self, request, response, code, msg, headers):
        raise urllib.error.HTTPError(request.full_url, code, msg, headers, response)

    def http_error_302(self, request, response, code, msg, headers):
        raise urllib.error.HTTPError(request.full_url, code, msg, headers, response)

    http_error_303 = http_error_302
    http_error_307 = http_error_302
    http_error_308 = http_error_302


def trigger_n8n_webhook(webhook_url: str, payload: dict) -> bool:
    """
    Dispatches the campaign payload to a live n8n webhook endpoint via HTTP POST.
    """
    parsed = urlparse(webhook_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Webhook URL must be an absolute HTTP(S) URL.")
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("Webhook URL must contain a hostname.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)}
        if any(ipaddress.ip_address(address).is_private or ipaddress.ip_address(address).is_loopback or ipaddress.ip_address(address).is_link_local for address in addresses):
            raise ValueError("Webhook URL cannot target a private, loopback, or link-local address.")
    except socket.gaierror as exc:
        raise ValueError("Webhook hostname could not be resolved.") from exc
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(req, timeout=5) as response:
            return response.status in [200, 201]
    except Exception as e:
        print(f"[n8n Dispatch Warning] Unable to reach webhook target: {e}")
        return False



def run_autonomous_campaign(
    product_name: str, 
    raw_image_path: str, 
    target_platform: str, 
    raw_video_path: Optional[str] = None, 
    webhook_url: str = "",
    output_dir: str = "outputs",
) -> dict:
    """
    Autonomous Director Agent that orchestrates asset creation, 
    builds a multi-channel schedule, and dispatches valid n8n workflow canvas structures.
    """
    print(f"\n[Director Agent] Initiating autonomous campaign execution: {product_name}")
    
    # 1. Visual Agent: Background removal & high-contrast optimization
    prompt = f"Remove background, place on clean studio background, optimize for {target_platform}."
    processed_image = run_image_agent(prompt, raw_image_path, output_dir=output_dir)
    
    # 2. Video Processing & Editing Agent
    print("[Director Agent] Triggering AI Video Processing Agent...")
    generated_video_path = None
    
    if raw_video_path and os.path.exists(raw_video_path):
        try:
            video_prompt = f"Auto edit for {product_name}: apply cinematic color preset, slow zoom in, add overlay text '{product_name.upper()}'."
            generated_video_path = run_editing_agent(video_prompt, [raw_video_path], output_dir=output_dir)
        except Exception as e:
            print(f"[Warning] Video editing agent fallback triggered: {e}")

    # 3. Content Roadmap Generation
    content_schedule = [
        {
            "topic": f"Introducing {product_name}: Launch Teaser", 
            "status": "Ready to Publish" if generated_video_path else "Unavailable: video asset missing", 
            "format": "9:16 Short / Reel",
            "media_type": "Processed Video" if generated_video_path else "Unavailable",
            "asset_ref": generated_video_path,
            "tags": "#3DAnimation #CreatorEconomy #Studio"
        },
        {
            "topic": f"3 Ways to Use {product_name} in Production", 
            "status": "In Queue" if processed_image else "Unavailable: image asset missing", 
            "format": "Carousel",
            "media_type": "Processed Image",
            "asset_ref": processed_image,
            "tags": "#Workflow #Design #Tech"
        },
        {
            "topic": f"Speedrun: Building {product_name} from Scratch", 
            "status": "Drafting" if generated_video_path else "Unavailable: video asset missing", 
            "format": "16:9 Longform",
            "media_type": "Combined Media",
            "asset_ref": "Bundle (Video + Image)",
            "tags": "#Tutorial #BehindTheScenes"
        }
    ]

    # 4. Valid n8n Workflow Canvas JSON (Importable directly into n8n canvas)
    n8n_payload = {
        "name": f"Omnichannel Auto-Publisher: {product_name}",
        "nodes": [
            {
                "parameters": {
                    "httpMethod": "POST",
                    "path": "campaign-webhook",
                    "options": {}
                },
                "name": "Webhook Trigger",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 1,
                "position": [250, 300]
            },
            {
                "parameters": {
                    "values": {
                        "string": [
                            {"name": "hero_image", "value": processed_image},
                            {"name": "promo_video", "value": generated_video_path},
                            {"name": "platform", "value": target_platform}
                        ]
                    }
                },
                "name": "Set Campaign Assets",
                "type": "n8n-nodes-base.set",
                "typeVersion": 1,
                "position": [450, 300]
            }
        ],
        "connections": {
            "Webhook Trigger": {
                "main": [
                    [
                        {
                            "node": "Set Campaign Assets",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            }
        },
        "settings": {},
        "tags": []
    }
    
    # Send payload if HTTP endpoint is supplied
    webhook_dispatched = False
    if webhook_url and webhook_url.strip():
        print(f"[Director Agent] Dispatching payload to n8n webhook: {webhook_url}")
        webhook_dispatched = trigger_n8n_webhook(webhook_url.strip(), n8n_payload)

    return {
        "campaign_name": product_name,
        "platform": target_platform,
        "assets": {
            "hero_image": processed_image,
            "promo_video": generated_video_path
        },
        "content_schedule": content_schedule,
        "n8n_payload": n8n_payload,
        "webhook_dispatched": webhook_dispatched,
        "status": "ready" if processed_image or generated_video_path else "unavailable",
    }