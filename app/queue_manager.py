import asyncio
import time
import uuid
import logging
from typing import Dict, Any, Optional, List, Deque
from datetime import datetime
from pydantic import BaseModel
import threading
from queue import PriorityQueue
import traceback
from collections import deque

class QueueItem(BaseModel):
    id: str
    api_key: str  # 사용자 API 키
    timestamp: float
    priority: int = 1
    model: str
    operation: str
    args: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    status: str = "pending"  # pending, processing, completed, failed
    google_api_key: Optional[str] = None  # 할당된 Google API 키
    
    def __lt__(self, other):
        # 우선순위 큐 정렬
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.timestamp < other.timestamp

class GoogleApiKeyManager:
    """Google API 키 관리자"""
    
    def __init__(self, api_keys: List[str], rpm_per_key: int = 15):
        if not api_keys:
            raise ValueError("API 키 목록이 비어 있습니다")
        
        self.api_keys = api_keys
        self.rpm_per_key = rpm_per_key
        self.key_locks = {key: threading.Lock() for key in api_keys}
        
        # 각 API 키별 요청 타임스탬프 추적
        self.key_timestamps: Dict[str, Deque[float]] = {
            key: deque(maxlen=rpm_per_key*2) for key in api_keys
        }
        
        # 각 API 키별 마지막 요청 시간
        self.last_request_times: Dict[str, float] = {key: 0 for key in api_keys}
        
        self.logger = logging.getLogger("api_key_manager")
        self.logger.info(f"Google API 키 관리자 초기화: {len(api_keys)}개 키, 키당 {rpm_per_key} RPM")
    
    def get_available_key(self) -> Optional[str]:
        """사용 가능한 API 키 반환"""
        current_time = time.time()
        best_key = None
        max_capacity = -1
        
        for key in self.api_keys:
            with self.key_locks[key]:
                # 1분보다 오래된 타임스탬프 제거
                minute_ago = current_time - 60
                self.key_timestamps[key] = deque(
                    [ts for ts in self.key_timestamps[key] if ts > minute_ago],
                    maxlen=self.key_timestamps[key].maxlen
                )
                
                # 현재 키의 여유 용량 계산
                available_capacity = self.rpm_per_key - len(self.key_timestamps[key])
                
                # 마지막 요청 이후 경과 시간
                time_since_last = current_time - self.last_request_times[key]
                
                # 최소 요청 간격
                min_interval = 60.0 / self.rpm_per_key
                
                # 간격 제한 확인
                interval_ok = time_since_last >= min_interval
                
                # 이 키가 더 많은 요청을 처리할 수 있고 간격이 적절하면 선택
                if available_capacity > max_capacity and interval_ok:
                    max_capacity = available_capacity
                    best_key = key
        
        return best_key
    
    def record_usage(self, key: str):
        """API 키 사용 기록"""
        current_time = time.time()
        with self.key_locks[key]:
            self.key_timestamps[key].append(current_time)
            self.last_request_times[key] = current_time
    
    def get_all_keys_status(self) -> Dict[str, Dict[str, Any]]:
        """모든 API 키의 상태 정보 반환"""
        current_time = time.time()
        result = {}
        
        for key in self.api_keys:
            with self.key_locks[key]:
                # 1분보다 오래된 타임스탬프 제거
                minute_ago = current_time - 60
                self.key_timestamps[key] = deque(
                    [ts for ts in self.key_timestamps[key] if ts > minute_ago],
                    maxlen=self.key_timestamps[key].maxlen
                )
                
                # 키 상태 정보
                result[key] = {
                    "requests_last_minute": len(self.key_timestamps[key]),
                    "available_capacity": self.rpm_per_key - len(self.key_timestamps[key]),
                    "last_used": self.last_request_times[key],
                    "time_since_last": current_time - self.last_request_times[key]
                }
        
        return result

class QueueManager:
    """요청 큐 관리자 (멀티 API 키 지원)"""
    
    def __init__(self, google_api_keys: List[str], rpm_per_key: int = 15, max_concurrent: int = 25):
        """큐 관리자 초기화"""
        self.queue = PriorityQueue()
        self.results: Dict[str, QueueItem] = {}
        self.lock = threading.Lock()
        self.processing_thread = None
        self.stop_event = threading.Event()
        self.logger = logging.getLogger("queue_manager")
        
        # Google API 키 관리자
        self.key_manager = GoogleApiKeyManager(google_api_keys, rpm_per_key)
        
        # 총 RPM = 키 개수 * 키당 RPM
        self.total_rpm = len(google_api_keys) * rpm_per_key
        self.logger.info(f"총 처리량: {self.total_rpm} RPM (키 {len(google_api_keys)}개 × {rpm_per_key} RPM)")
        
        # 활성 요청 추적
        self.active_requests = 0
        self.max_concurrent = max_concurrent  # 동시 처리 최대 요청 수
        self.active_lock = threading.Lock()
        
    def start_processing(self):
        """처리 스레드 시작"""
        if self.processing_thread is None or not self.processing_thread.is_alive():
            self.stop_event.clear()
            self.processing_thread = threading.Thread(target=self._process_queue, daemon=True)
            self.processing_thread.start()
            self.logger.info("큐 처리 스레드 시작")
    
    def stop_processing(self):
        """처리 스레드 중지"""
        if self.processing_thread and self.processing_thread.is_alive():
            self.stop_event.set()
            self.processing_thread.join(timeout=5.0)
            self.logger.info("큐 처리 스레드 중지")
    
    def enqueue_request(self, api_key: str, model: str, operation: str, args: Dict[str, Any], priority: int = 1) -> str:
        """요청을 큐에 추가하고 요청 ID 반환"""
        request_id = str(uuid.uuid4())
        item = QueueItem(
            id=request_id,
            api_key=api_key,
            timestamp=time.time(),
            priority=priority,
            model=model,
            operation=operation,
            args=args,
            status="pending"
        )
        
        # 큐와 결과 딕셔너리에 추가
        with self.lock:
            self.queue.put(item)
            self.results[request_id] = item
        
        self.logger.info(f"요청 {request_id} 큐에 추가. 현재 큐 크기: {self.queue.qsize()}")
        
        # 처리 스레드 실행 확인
        self.start_processing()
        
        return request_id
    
    def get_request_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        """요청 ID로 상태 정보 조회"""
        with self.lock:
            if request_id in self.results:
                item = self.results[request_id]
                return {
                    "id": item.id,
                    "status": item.status,
                    "result": item.result,
                    "error": item.error,
                    "timestamp": item.timestamp,
                    "google_api_key": item.google_api_key  # 어떤 Google API 키가 사용되었는지 추적
                }
        return None
    
    def clean_old_results(self, max_age_seconds: int = 3600):
        """오래된 결과 정리"""
        current_time = time.time()
        with self.lock:
            keys_to_remove = [
                key for key, item in self.results.items()
                if item.status in ["completed", "failed"] and 
                (current_time - item.timestamp) > max_age_seconds
            ]
            
            for key in keys_to_remove:
                del self.results[key]
                
        if keys_to_remove:
            self.logger.info(f"{len(keys_to_remove)}개 오래된 결과 정리 완료")
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """큐 상태 통계 반환"""
        with self.lock:
            pending_count = sum(1 for item in self.results.values() if item.status == "pending")
            processing_count = sum(1 for item in self.results.values() if item.status == "processing")
            completed_count = sum(1 for item in self.results.values() if item.status == "completed")
            failed_count = sum(1 for item in self.results.values() if item.status == "failed")
            
        with self.active_lock:
            active = self.active_requests
        
        return {
            "queue_size": self.queue.qsize(),
            "pending": pending_count,
            "processing": processing_count,
            "completed": completed_count,
            "failed": failed_count,
            "active_requests": active,
            "total_rpm": self.total_rpm,
            "api_keys": len(self.key_manager.api_keys),
            "api_key_status": self.key_manager.get_all_keys_status()
        }
    
    def _can_start_new_request(self) -> bool:
        """새 요청을 시작할 수 있는지 확인"""
        with self.active_lock:
            return self.active_requests < self.max_concurrent
    
    def _process_queue(self):
        """큐 처리 메인 루프"""
        from app.client import gemini_client  # 순환 임포트 방지
        
        self.logger.info("큐 처리기 시작")
        
        while not self.stop_event.is_set():
            try:
                # 오래된 결과 정리
                self.clean_old_results()
                
                # 큐가 비어 있으면 대기
                if self.queue.empty():
                    time.sleep(0.5)
                    continue
                
                # 동시 요청 제한 확인
                if not self._can_start_new_request():
                    time.sleep(0.1)  # 다음 검사까지 짧게 대기
                    continue
                
                # 사용 가능한 API 키 확인
                google_api_key = self.key_manager.get_available_key()
                if not google_api_key:
                    # 모든 키가 RPM 제한에 도달했거나 간격 제한 중이면 대기
                    time.sleep(0.2)
                    continue
                
                # 요청 가져오기
                try:
                    item = self.queue.get(block=False)
                except Exception:
                    time.sleep(0.1)
                    continue
                
                # 상태 업데이트 및 API 키 할당
                with self.lock:
                    item.status = "processing"
                    item.google_api_key = google_api_key  # 요청에 사용한 Google API 키 기록
                    self.results[item.id] = item
                
                # API 키 사용 기록
                self.key_manager.record_usage(google_api_key)
                
                # 활성 요청 카운터 증가
                with self.active_lock:
                    self.active_requests += 1
                
                self.logger.info(f"요청 {item.id} 처리 중 (API 키: {google_api_key[-6:]})")
                
                # 백그라운드 스레드에서 요청 처리
                thread = threading.Thread(
                    target=self._execute_request,
                    args=(gemini_client, item, google_api_key),
                    daemon=True
                )
                thread.start()
                
                # 큐 작업 완료 표시
                self.queue.task_done()
                
            except Exception as e:
                self.logger.error(f"큐 처리 오류: {str(e)}")
                self.logger.error(traceback.format_exc())
                time.sleep(0.5)
        
        self.logger.info("큐 처리기 중지")
    
    def _execute_request(self, client, item, google_api_key):
        """백그라운드 스레드에서 요청 실행"""
        try:
            # 현재 API 키로 클라이언트 설정
            client.set_api_key(google_api_key)
            
            # 요청 실행
            operation_func = getattr(client, item.operation)
            result = operation_func(**item.args)
            
            # 결과 업데이트
            with self.lock:
                item.result = result
                item.status = "completed"
                self.results[item.id] = item
            
            self.logger.info(f"요청 {item.id} 성공 완료 (API 키: {google_api_key[-6:]})")
            
        except Exception as e:
            # 오류 정보 업데이트
            error_message = str(e)
            self.logger.error(f"요청 {item.id} 실패 (API 키: {google_api_key[-6:]}): {error_message}")
            self.logger.error(traceback.format_exc())
            
            with self.lock:
                item.error = error_message
                item.status = "failed"
                self.results[item.id] = item
        
        finally:
            # 활성 요청 카운터 감소
            with self.active_lock:
                self.active_requests -= 1

# 공유 큐 관리자 인스턴스 생성
# app.client.py에서 GOOGLE_API_KEYS 가져오기
from app.client import GOOGLE_API_KEYS
queue_manager = QueueManager(google_api_keys=GOOGLE_API_KEYS, rpm_per_key=15, max_concurrent=25)
