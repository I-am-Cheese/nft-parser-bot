"""
Асинхронная очередь задач для обработки парсинга
"""
import asyncio
import time
from typing import Optional, Callable, Any, Dict
from dataclasses import dataclass
from enum import Enum

from config import NUM_WORKERS, MAX_QUEUE_SIZE


class TaskStatus(str, Enum):
    """Статус задачи"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """Задача в очереди"""
    task_id: str
    user_id: int
    task_type: str  # 'random', 'female'
    collection: str
    callback: Callable
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: float = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
    
    def get_duration(self) -> Optional[float]:
        """Получить длительность выполнения"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None


class AsyncTaskQueue:
    """
    Асинхронная очередь задач с пулом воркеров
    
    Args:
        num_workers: Количество воркеров (по умолчанию 5)
        max_size: Максимальный размер очереди (по умолчанию 100)
    """
    
    def __init__(self, num_workers: int = 5, max_size: int = MAX_QUEUE_SIZE):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self.num_workers = num_workers
        self.max_size = max_size
        self.workers: list = []
        self.tasks: Dict[str, Task] = {}  # task_id -> Task
        self._running = False
        
        # Статистика
        self.total_processed = 0
        self.total_failed = 0
    
    async def start(self):
        """Запустить воркеры"""
        if self._running:
            return
        
        self._running = True
        self.workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self.num_workers)
        ]
        print(f"✅ Запущено {self.num_workers} воркеров")
    
    async def stop(self):
        """Остановить воркеры"""
        self._running = False
        
        # Отменяем все воркеры
        for worker in self.workers:
            worker.cancel()
        
        # Ждём завершения
        await asyncio.gather(*self.workers, return_exceptions=True)
        print("✅ Воркеры остановлены")
    
    async def _worker(self, worker_id: int):
        """Воркер для обработки задач"""
        print(f"🔄 Воркер {worker_id} запущен")
        
        while self._running:
            try:
                # Получаем задачу из очереди
                task: Task = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=1.0
                )
                
                # Обрабатываем задачу
                await self._process_task(task, worker_id)
                
                # Помечаем задачу как выполненную
                self.queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Ошибка в воркере {worker_id}: {e}")
    
    async def _process_task(self, task: Task, worker_id: int):
        """Обработать задачу"""
        task.status = TaskStatus.PROCESSING
        task.started_at = time.time()
        
        print(f"⚙️ Воркер {worker_id} обрабатывает задачу {task.task_id}")
        
        try:
            # Выполняем callback
            result = await task.callback(task.collection, task.user_id)
            
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            
            self.total_processed += 1
            
            duration = task.get_duration()
            print(f"✅ Задача {task.task_id} выполнена за {duration:.1f}с")
            
        except Exception as e:
            task.error = str(e)
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()
            
            self.total_failed += 1
            
            print(f"❌ Задача {task.task_id} завершилась с ошибкой: {e}")
    
    async def add_task(
        self,
        task_id: str,
        user_id: int,
        task_type: str,
        collection: str,
        callback: Callable
    ) -> bool:
        """
        Добавить задачу в очередь
        
        Returns:
            True если задача добавлена, False если очередь переполнена
        """
        if self.queue.full():
            return False
        
        task = Task(
            task_id=task_id,
            user_id=user_id,
            task_type=task_type,
            collection=collection,
            callback=callback
        )
        
        self.tasks[task_id] = task
        await self.queue.put(task)
        
        print(f"📥 Задача {task_id} добавлена в очередь (размер: {self.queue.qsize()})")
        return True
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Получить задачу по ID"""
        return self.tasks.get(task_id)
    
    def get_queue_size(self) -> int:
        """Получить размер очереди"""
        return self.queue.qsize()
    
    def get_stats(self) -> Dict[str, int]:
        """Получить статистику"""
        return {
            "queue_size": self.queue.qsize(),
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "pending_tasks": len([t for t in self.tasks.values() if t.status == TaskStatus.PENDING]),
            "processing_tasks": len([t for t in self.tasks.values() if t.status == TaskStatus.PROCESSING]),
        }
    
    async def wait_for_task(self, task_id: str, timeout: float = 300) -> Optional[Task]:
        """
        Ждать завершения задачи
        
        Args:
            task_id: ID задачи
            timeout: Таймаут в секундах
        
        Returns:
            Task если завершена, None если таймаут
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            task = self.get_task(task_id)
            
            if not task:
                return None
            
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                return task
            
            await asyncio.sleep(0.5)
        
        return None


# Singleton

task_queue = AsyncTaskQueue(num_workers=NUM_WORKERS, max_size=MAX_QUEUE_SIZE)
