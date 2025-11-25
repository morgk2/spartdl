#!/usr/bin/env python3
"""
Performance Test Script for SpotDL API
Tests the optimized async endpoints and caching
"""

import requests
import time
import json
from typing import Dict

API_BASE_URL = "http://localhost:8000"

def test_api_health():
    """Test if API is running"""
    print("🔍 Testing API health...")
    try:
        response = requests.get(f"{API_BASE_URL}/")
        if response.status_code == 200:
            print("✅ API is running!")
            print(f"   Response: {response.json()}")
            return True
        else:
            print(f"❌ API returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Failed to connect to API: {e}")
        print(f"   Make sure the API is running on {API_BASE_URL}")
        return False

def test_async_download(spotify_url: str):
    """Test the new async download endpoint"""
    print(f"\n🎵 Testing async download...")
    print(f"   URL: {spotify_url}")
    
    # Submit download request
    start_time = time.time()
    try:
        response = requests.post(
            f"{API_BASE_URL}/get/audio-download-link",
            json={
                "spotify_url": spotify_url,
                "format": "mp3",
                "quality": "best"
            }
        )
        
        submission_time = time.time() - start_time
        print(f"✅ Request submitted in {submission_time:.2f}s")
        
        if response.status_code != 200:
            print(f"❌ Failed: {response.text}")
            return None
            
        data = response.json()
        
        # Check if cached
        if data.get("cached"):
            print(f"⚡ CACHED! Instant response!")
            print(f"   Download URL: {data['audio_download_url']}")
            return data
        
        task_id = data.get("task_id")
        if not task_id:
            print(f"❌ No task_id in response: {data}")
            return None
            
        print(f"   Task ID: {task_id}")
        print(f"   Status URL: {data['status_url']}")
        
        # Poll for completion
        print(f"\n⏳ Polling for completion...")
        poll_count = 0
        max_polls = 60  # 2 minutes max (2s interval)
        
        while poll_count < max_polls:
            time.sleep(2)  # Poll every 2 seconds
            poll_count += 1
            
            status_response = requests.get(f"{API_BASE_URL}/status/{task_id}")
            if status_response.status_code != 200:
                print(f"❌ Failed to get status: {status_response.text}")
                return None
                
            status = status_response.json()
            current_status = status.get("status")
            
            elapsed = time.time() - start_time
            print(f"   [{elapsed:.1f}s] Status: {current_status}")
            
            if current_status == "completed":
                total_time = time.time() - start_time
                print(f"✅ Download completed in {total_time:.2f}s!")
                print(f"   Download URL: {status.get('file_path')}")
                return status
            elif current_status == "failed":
                print(f"❌ Download failed: {status.get('error')}")
                return None
            elif current_status in ["queued", "downloading"]:
                continue
            else:
                print(f"⚠️  Unknown status: {current_status}")
                
        print(f"❌ Timeout after {max_polls * 2}s")
        return None
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def test_cache_performance(spotify_url: str):
    """Test cache performance by making the same request twice"""
    print(f"\n🔄 Testing cache performance...")
    
    # First request
    print(f"\n--- First Request (no cache) ---")
    start1 = time.time()
    result1 = test_async_download(spotify_url)
    time1 = time.time() - start1
    
    if not result1:
        print("❌ First request failed, cannot test cache")
        return
    
    # Wait a moment
    time.sleep(2)
    
    # Second request (should be cached)
    print(f"\n--- Second Request (should be cached) ---")
    start2 = time.time()
    result2 = test_async_download(spotify_url)
    time2 = time.time() - start2
    
    if not result2:
        print("❌ Second request failed")
        return
    
    # Compare performance
    print(f"\n📊 Performance Comparison:")
    print(f"   First request:  {time1:.2f}s")
    print(f"   Second request: {time2:.2f}s")
    if result2.get("cached"):
        speedup = time1 / time2 if time2 > 0 else float('inf')
        print(f"   ⚡ Cache speedup: {speedup:.1f}x faster!")
    else:
        print(f"   ⚠️  Second request was not cached")

def test_list_tasks():
    """Test listing all tasks"""
    print(f"\n📋 Listing all tasks...")
    try:
        response = requests.get(f"{API_BASE_URL}/tasks")
        if response.status_code == 200:
            tasks = response.json().get("tasks", [])
            print(f"✅ Found {len(tasks)} task(s)")
            for task in tasks[:5]:  # Show first 5
                print(f"   - {task['task_id']}: {task['status']}")
        else:
            print(f"❌ Failed to list tasks: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    """Run performance tests"""
    print("=" * 60)
    print("SpotDL API Performance Test Suite")
    print("=" * 60)
    
    # Test API health
    if not test_api_health():
        return
    
    # Example Spotify URL (replace with a real one)
    # This is a short track for testing
    spotify_url = input("\n🎵 Enter a Spotify track URL to test (or press Enter for example): ").strip()
    
    if not spotify_url:
        print("\n⚠️  Using example URL - this may not work!")
        print("   Please provide a real Spotify track URL for accurate testing")
        spotify_url = "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp"
    
    # Run tests
    print("\n" + "=" * 60)
    print("Test 1: Async Download Performance")
    print("=" * 60)
    test_async_download(spotify_url)
    
    print("\n" + "=" * 60)
    print("Test 2: Cache Performance")
    print("=" * 60)
    test_cache_performance(spotify_url)
    
    # List tasks
    test_list_tasks()
    
    print("\n" + "=" * 60)
    print("✅ Tests completed!")
    print("=" * 60)
    print("\n💡 Tips:")
    print("   - First requests take 15-30s (actual download time)")
    print("   - Cached requests should be instant (<1s)")
    print("   - Check PERFORMANCE_GUIDE.md for more details")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
