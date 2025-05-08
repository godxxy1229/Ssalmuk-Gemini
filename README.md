# Ssalmuk_Gemini
I’m using the Gemini API Free plan, but I still wanted higher RPM (Requests Per Minute), so I built my own proxy server. The server generates and manages its own API keys, so by using my own API, I can make high-volume requests—basically as many as the number of accounts I have.

---

This solution speeds up processing time based on the number of free plan API keys you have.

The idea is simple: it always picks the API key with the most available quota, and if a key hits its RPM (Requests Per Minute) limit, it automatically switches to another. It also supports multiple concurrent requests (`max_concurrent` setting), and each request runs in its own thread.

> The following table shows the estimated Requests Per Minute (RPM), Requests Per Second (RPS), and Daily Request Capacity depending on the number of API keys, assuming you're using the **Gemini 2.0 Flash model**.
> 
> *As of April 2025, each API key supports 15 RPM and 1500 requests per day.*

| Number of API Keys | Total RPM (per minute) | RPS (per second) | Daily Limit (requests/day) |
| ------------------ | ---------------------- | ---------------- | -------------------------- |
| 1                  | 15                     | 0.25             | 1,500                      |
| 4                  | 60                     | 1.00             | 6,000                      |
| 10                 | 150                    | 2.50             | 15,000                     |
| 20                 | 300                    | 5.00             | 30,000                     |
| 100                | 1500                   | 25.00            | 150,000                    |

---

## How to use:

### Set your Google API keys:

Place your 10 Google API keys in an environment variable:

    export GOOGLE_API_KEYS="key1,key2,key3,key4,key5,key6,key7,key8,key9,key10"

Using Docker:

    docker-compose up -d

Or directly(venv recommended):

    source gemini_env/bin/activate
    uvicorn app.main:app --reload

Access the API documentation:

    http://localhost:8000/admin/keys

Make requests to Gemini through your API:

(Example: Creating 10 STT results each with 5 different temperatures options.)

    import requests
    import time
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # 기본 설정
    API_URL = "http://192.168.0.100:8888/api/generate"
    STATUS_URL = "http://192.168.0.100:8888/api/status/"
    API_KEY = "Your-API-Key"
    
    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }
    
    # 1. 파일 업로드
    upload_response = requests.post(
        "http://192.168.0.100:8888/api/files/upload",
        headers={"X-API-Key": API_KEY},
        files={"file": open("sample.mp3", "rb")}
    )
    file_id = upload_response.json()["id"]
    
    # 2. 프롬프트 설정
    prompt = "Your-Prompt-Here"
    
    temperatures = [0.2, 0.6, 1.0, 1.4, 1.8]
    
    # 3. 요청 생성
    def submit_request(temp, run_index):
        data = {
            "model": "gemini-2.0-flash-lite",
            "contents": [prompt, {"file_id": file_id}],
            "config": {"temperature": temp},
            "wait": False
        }
        try:
            response = requests.post(API_URL, headers=headers, json=data)
            request_id = response.json()["request_id"]
            return {"request_id": request_id, "temperature": temp, "run_index": run_index, "submit_time": time.time()}
        except Exception as e:
            return {"request_id": None, "temperature": temp, "run_index": run_index, "error": str(e)}
    
    # 4. 상태 확인
    def poll_status(entry):
        request_id = entry["request_id"]
        if not request_id:
            return {**entry, "status": "failed", "output": "Request failed"}
    
        while True:
            try:
                status_response = requests.get(STATUS_URL + request_id, headers=headers)
                status_data = status_response.json()
                if status_data["status"] in ["completed", "failed"]:
                    elapsed = round(time.time() - entry["submit_time"], 2)
                    return {
                        **entry,
                        "status": status_data["status"],
                        "output": status_data.get("text", "No output"),
                        "elapsed_time_sec": elapsed
                    }
                time.sleep(5)
            except Exception as e:
                return {**entry, "status": "failed", "output": f"Polling error: {e}"}
    
    # 5. 요청 + Polling 실행
    submitted = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for temp in temperatures:
            for i in range(10):
                futures.append(executor.submit(submit_request, temp, i + 1))
                time.sleep(1)  # RPM 15 이하 유지용 딜레이
    
        for future in as_completed(futures):
            submitted.append(future.result())
    
    # 6. 상태 폴링
    final_results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(poll_status, entry) for entry in submitted]
        for future in as_completed(futures):
            final_results.append(future.result())
    
    # 7. 저장
    df = pd.DataFrame(final_results)
    df.to_csv("polling_test_results.csv", index=False, encoding='utf-8-sig')
    print("✅ Saved: polling_test_results.csv")
