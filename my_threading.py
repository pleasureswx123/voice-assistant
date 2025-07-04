"""
MicroPython线程库实现
提供了线程同步原语和线程池功能

主要特性:
- 可重入锁 (Lock)
- 条件变量 (Condition)
- 事件 (Event)
- 信号量 (Semaphore)
- 队列 (Queue, LifoQueue, PriorityQueue)
- 线程池 (ThreadPoolExecutor)
- 异步任务 (AsyncTask)

注意事项:
1. 该实现依赖MicroPython特定模块
2. 使用Thread.terminate()时需要特别注意资源释放
3. 建议定期进行垃圾回收以避免内存泄漏
"""

import utime
import sys
import _thread
import osTimer
import gc
from typing import Any, Callable, List, Optional, Set, Tuple, Union


class Lock:
    """可重入锁实现
    
    特性:
    - 支持可重入
    - 支持超时
    - 支持上下文管理器
    - 包含死锁检测
    
    示例:
        lock = Lock()
        with lock:
            # 临界区代码
            pass
    """
    
    def __init__(self):
        self.__lock = _thread.allocate_lock()
        self.__owner = None  # 当前持有锁的线程ID
        self.__locked_count = 0  # 重入计数
        self.__waiting_threads = set()  # 等待获取锁的线程集合
        self.__last_acquire_time = 0  # 上次成功获取锁的时间

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        
    def _check_deadlock(self) -> bool:
        """检查是否可能发生死锁"""
        current_thread = _thread.get_ident()
        # 如果当前线程已经在等待队列中且持有锁的线程也在等待其他锁
        if current_thread in self.__waiting_threads and self.__owner in self.__waiting_threads:
            return True
        # 如果锁被持有时间过长（超过30秒）
        if self.__locked_count > 0 and utime.ticks_diff(utime.ticks_ms(), self.__last_acquire_time) > 30000:
            return True
        return False

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """获取锁
        
        Args:
            timeout: 超时时间（秒），None表示永不超时
            
        Returns:
            bool: 是否成功获取锁
            
        Raises:
            RuntimeError: 检测到可能的死锁
        """
        current_thread = _thread.get_ident()
        
        # 如果当前线程已经持有锁，增加计数
        if self.__owner == current_thread:
            self.__locked_count += 1
            return True
            
        self.__waiting_threads.add(current_thread)
        try:
            # 检查死锁
            if self._check_deadlock():
                raise RuntimeError("Potential deadlock detected")
                
            if timeout is not None:
                end_time = utime.ticks_add(utime.ticks_ms(), int(timeout * 1000))
                while not self.__lock.acquire():
                    if utime.ticks_diff(end_time, utime.ticks_ms()) <= 0:
                        return False
                    utime.sleep_ms(1)
            else:
                self.__lock.acquire()
            
            self.__owner = current_thread
            self.__locked_count = 1
            self.__last_acquire_time = utime.ticks_ms()
            return True
            
        finally:
            self.__waiting_threads.remove(current_thread)

    def release(self):
        """释放锁
        
        Raises:
            RuntimeError: 尝试释放未持有的锁
        """
        if self.__owner != _thread.get_ident():
            raise RuntimeError("cannot release un-owned lock")
            
        self.__locked_count -= 1
        if self.__locked_count == 0:
            self.__owner = None
            self.__last_acquire_time = 0
            return self.__lock.release()

    def locked(self) -> bool:
        """返回锁是否被持有"""
        return self.__lock.locked()

    @property
    def owner(self) -> Optional[int]:
        """返回持有锁的线程ID"""
        return self.__owner
        
    @property
    def waiting_threads(self) -> Set[int]:
        """返回等待获取锁的线程集合"""
        return self.__waiting_threads.copy()


class _Waiter:
    """WARNING: Waiter object can only be used once."""

    def __init__(self):
        self.__lock = Lock()
        self.__lock.acquire()
        self.__gotit = True
        self.__timer = None
        self.__timer_lock = Lock()

    def __auto_release(self, _: Any) -> None:
        with self.__timer_lock:
            self.__gotit = not self.__release()
            if self.__timer:
                self.__timer.stop()
                self.__timer = None

    def acquire(self, timeout: Optional[float] = None) -> bool:
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        
        gotit = self.__gotit
        if timeout:
            with self.__timer_lock:
                if not self.__timer:
                    self.__timer = osTimer()
                self.__timer.start(int(timeout * 1000), 0, self.__auto_release)
        
        self.__lock.acquire()
        
        if timeout:
            with self.__timer_lock:
                gotit = self.__gotit
                if self.__timer:
                    self.__timer.stop()
                    self.__timer = None
        
        return gotit

    def __release(self) -> bool:
        try:
            self.__lock.release()
            return True
        except RuntimeError:
            return False

    def release(self) -> bool:
        return self.__release()

    def __del__(self) -> None:
        if self.__timer:
            self.__timer.stop()
            self.__timer = None


class Condition(object):

    def __init__(self, lock=None):
        self.__lock = lock or Lock()
        self.__waiters = []
        self.acquire = self.__lock.acquire
        self.release = self.__lock.release

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args, **kwargs):
        self.release()

    def __is_owned(self):
        return self.__lock.locked() and self.__lock.owner == _thread.get_ident()

    def wait(self, timeout=None):
        if not self.__is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")
        
        waiter = _Waiter()
        self.__waiters.append(waiter)
        self.release()
        
        try:
            gotit = waiter.acquire(timeout)
            return gotit
        finally:
            self.acquire()
            if not gotit:
                try:
                    self.__waiters.remove(waiter)
                except ValueError:
                    pass
            gc.collect()  # 清理不再使用的waiter对象

    def wait_for(self, predicate, timeout=None):
        result = predicate()
        if result:
            return result

        if timeout is not None:
            end_time = utime.ticks_add(utime.ticks_ms(), int(timeout * 1000))
        
        while not result:
            if timeout is not None:
                remaining = utime.ticks_diff(end_time, utime.ticks_ms()) / 1000
                if remaining <= 0:
                    break
                result = self.wait(remaining) and predicate()
            else:
                result = self.wait() and predicate()
        
        return result

    def notify(self, n=1):
        if not self.__is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")
        
        if n < 0:
            n = 0
        
        waiters = self.__waiters[:n]
        for waiter in waiters:
            waiter.release()
            try:
                self.__waiters.remove(waiter)
            except ValueError:
                pass
        
        if len(waiters) > 0:
            gc.collect()  # 清理已通知的waiter对象

    def notify_all(self):
        self.notify(len(self.__waiters))


class Event(object):

    def __init__(self):
        self.__flag = False
        self.__cond = Condition()

    def wait(self, timeout=None, clear=False):
        with self.__cond:
            result = self.__cond.wait_for(lambda: self.__flag, timeout=timeout)
            if result and clear:
                self.__flag = False
            return result

    def set(self):
        with self.__cond:
            self.__flag = True
            self.__cond.notify_all()

    def clear(self):
        with self.__cond:
            self.__flag = False

    def is_set(self):
        with self.__cond:
            return self.__flag


class EventSet(object):

    def __init__(self):
        self.__set = 0
        self.__cond = Condition()
    
    def wait(self, event_set, timeout=None, clear=False):
        with self.__cond:
            result = self.__cond.wait_for(
                lambda: (event_set & self.__set) == event_set,
                timeout=timeout
            )
            if result and clear:
                self.__set &= ~event_set
            return result
    
    def waitAny(self, event_set, timeout=None, clear=False):
        with self.__cond:
            result = self.__cond.wait_for(
                lambda: bool(event_set & self.__set),
                timeout=timeout
            )
            if result and clear:
                self.__set &= ~event_set
            return result
    
    def set(self, event_set):
        with self.__cond:
            self.__set |= event_set
            self.__cond.notify_all()

    def clear(self, event_set):
        with self.__cond:
            self.__set &= ~event_set
    
    def is_set(self, event_set):
        with self.__cond:
            return (self.__set & event_set) == event_set
    
    def is_set_any(self, event_set):
        with self.__cond:
            return bool(self.__set & event_set)


class Semaphore(object):

    def __init__(self, value=1):
        if value < 0:
            raise ValueError("semaphore initial value must be >= 0")
        self.__value = value
        self.__cond = Condition()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args, **kwargs):
        self.release()

    def counts(self):
        with self.__cond:
            return self.__value

    def acquire(self, block=True, timeout=None):
        with self.__cond:
            if not block:
                if self.__value > 0:
                    self.__value -= 1
                    return True
                return False
            
            if timeout is not None and timeout <= 0:
                raise ValueError("timeout must be positive")
            
            if self.__cond.wait_for(lambda: self.__value > 0, timeout=timeout):
                self.__value -= 1
                return True
            return False

    def release(self, n=1):
        if n < 1:
            raise ValueError("n must be one or more")
        with self.__cond:
            self.__value += n
            self.__cond.notify(n)

    def clear(self):
        with self.__cond:
            self.__value = 0


class BoundedSemaphore(Semaphore):

    def __init__(self, value=1):
        super().__init__(value)
        self.__initial_value = value

    def release(self, n=1):
        if n < 1:
            raise ValueError("n must be one or more")
        with self.__cond:
            if self.__value + n > self.__initial_value:
                raise ValueError("Semaphore released too many times")
            self.__value += n
            self.__cond.notify(n)


class Queue(object):
    
    class Full(Exception):
        pass

    class Empty(Exception):
        pass

    def __init__(self, max_size=100):
        self.queue = []
        self.__max_size = max_size
        self.__lock = Lock()
        self.__not_empty = Condition(self.__lock)
        self.__not_full = Condition(self.__lock)

    def _put(self, item):
        self.queue.append(item)

    def put(self, item, block=True, timeout=None):
        with self.__not_full:
            if not block:
                if len(self.queue) >= self.__max_size:
                    raise self.Full
            elif timeout is not None and timeout <= 0:
                raise ValueError("timeout must be positive")
            else:
                if not self.__not_full.wait_for(
                    lambda: len(self.queue) < self.__max_size,
                    timeout=timeout
                ):
                    raise self.Full
            self._put(item)
            self.__not_empty.notify()

    def _get(self):
        return self.queue.pop(0)

    def get(self, block=True, timeout=None):
        with self.__not_empty:
            if not block:
                if len(self.queue) == 0:
                    raise self.Empty
            elif timeout is not None and timeout <= 0:
                raise ValueError("timeout must be positive")
            else:
                if not self.__not_empty.wait_for(
                    lambda: len(self.queue) > 0,
                    timeout=timeout
                ):
                    raise self.Empty
            item = self._get()
            self.__not_full.notify()
            return item

    def size(self):
        with self.__lock:
            return len(self.queue)

    def clear(self):
        with self.__lock:
            self.queue.clear()
            self.__not_full.notify_all()


class LifoQueue(Queue):

    def _put(self, item):
        self.queue.append(item)

    def _get(self):
        return self.queue.pop()


class PriorityQueue(Queue):

    @staticmethod
    def __siftdown(heap, startpos, pos):
        newitem = heap[pos]
        while pos > startpos:
            parentpos = (pos - 1) >> 1
            parent = heap[parentpos]
            if newitem < parent:
                heap[pos] = parent
                pos = parentpos
                continue
            break
        heap[pos] = newitem

    def _put(self, item):
        self.queue.append(item)
        self.__siftdown(self.queue, 0, len(self.queue) - 1)

    @staticmethod
    def __siftup(heap, pos):
        endpos = len(heap)
        startpos = pos
        newitem = heap[pos]
        childpos = 2 * pos + 1
        while childpos < endpos:
            rightpos = childpos + 1
            if rightpos < endpos and not heap[childpos] < heap[rightpos]:
                childpos = rightpos
            heap[pos] = heap[childpos]
            pos = childpos
            childpos = 2 * pos + 1
        heap[pos] = newitem
        PriorityQueue.__siftdown(heap, startpos, pos)

    def _get(self):
        lastelt = self.queue.pop()
        if self.queue:
            returnitem = self.queue[0]
            self.queue[0] = lastelt
            self.__siftup(self.queue, 0)
            return returnitem
        return lastelt


class Thread(object):
    DEFAULT_STACK_SIZE = _thread.stack_size()

    def __init__(self, target=None, args=(), kwargs=None):
        self.__target = target
        self.__args = args
        self.__kwargs = kwargs or {}
        self.__ident = None
        self.__stopped_event = Event()
        self.__started = False

    def is_running(self):
        return self.__ident is not None and _thread.threadIsRunning(self.__ident)

    def join(self, timeout=None):
        if not self.__started:
            raise RuntimeError("cannot join thread before it is started")
        return self.__stopped_event.wait(timeout=timeout)

    def terminate(self):
        """WARNING: you must release all resources after terminate thread, especially **Lock(s)**"""
        if self.is_running():
            _thread.stop_thread(self.ident)
            self.__ident = None
        self.__stopped_event.set()

    def start(self, stack_size=None):
        if self.__started:
            raise RuntimeError("thread already started")
        if stack_size is not None:
            _thread.stack_size(stack_size * 1024)
        try:
            self.__ident = _thread.start_new_thread(self.__bootstrap, ())
            self.__started = True
        finally:
            if stack_size is not None:
                _thread.stack_size(self.DEFAULT_STACK_SIZE)

    def __bootstrap(self):
        try:
            self.run()
        except Exception as e:
            sys.print_exception(e)
        finally:
            self.__stopped_event.set()
            gc.collect()  # 清理线程资源

    def run(self):
        if self.__target:
            self.__target(*self.__args, **self.__kwargs)

    @property
    def ident(self):
        return self.__ident


class _Result:
    """任务结果封装类"""

    class TimeoutError(Exception):
        """获取结果超时异常"""
        pass

    class NotReadyError(Exception):
        """结果未就绪异常"""
        pass

    def __init__(self):
        self.__rv = None
        self.__exc = None
        self.__finished = Event()

    def set(self, exc: Optional[Exception] = None, rv: Any = None) -> None:
        """设置结果或异常
        
        Args:
            exc: 异常对象
            rv: 返回值
        """
        self.__exc = exc
        self.__rv = rv
        self.__finished.set()

    def __get_value_or_raise_exc(self) -> Any:
        """获取结果值或抛出异常"""
        if self.__exc:
            raise self.__exc
        return self.__rv

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Any:
        """获取结果
        
        Args:
            block: 是否阻塞等待
            timeout: 超时时间（秒）
            
        Returns:
            Any: 任务的返回值
            
        Raises:
            TimeoutError: 等待超时
            NotReadyError: 结果未就绪（非阻塞模式）
        """
        if not block:
            if self.__finished.is_set():
                return self.__get_value_or_raise_exc()
            raise self.NotReadyError("result not ready")
        
        if self.__finished.wait(timeout=timeout):
            return self.__get_value_or_raise_exc()
        raise self.TimeoutError("get result timeout")


class AsyncTask:
    """异步任务实现
    
    特性:
    - 支持延迟执行
    - 支持超时控制
    - 支持任务状态监控
    - 支持取消任务
    
    示例:
        @AsyncTask.wrapper
        def my_task(x, y):
            return x + y
            
        task = my_task(1, 2)
        result = task.delay().get(timeout=5)
    """
    
    class Status:
        PENDING = 'PENDING'
        RUNNING = 'RUNNING'
        COMPLETED = 'COMPLETED'
        FAILED = 'FAILED'
        CANCELLED = 'CANCELLED'
    
    def __init__(self, target: Callable, args: tuple = (), kwargs: dict = None):
        self.__target = target
        self.__args = args
        self.__kwargs = kwargs or {}
        self.__status = self.Status.PENDING
        self.__start_time = None
        self.__end_time = None
        self.__thread = None
        self.__result = None
        self.__error = None
        self.__lock = Lock()

    def delay(self, seconds: Optional[float] = None) -> '_Result':
        """延迟执行任务
        
        Args:
            seconds: 延迟时间（秒）
            
        Returns:
            _Result: 用于获取任务结果的对象
        """
        with self.__lock:
            if self.__status != self.Status.PENDING:
                raise RuntimeError("Task already started")
                
            self.__result = _Result()
            self.__thread = Thread(target=self.__run, args=(seconds,))
            self.__thread.start()
            return self.__result

    def __run(self, delay_seconds: Optional[float]):
        """任务执行函数"""
        try:
            with self.__lock:
                self.__status = self.Status.RUNNING
                self.__start_time = utime.ticks_ms()
                
            if delay_seconds is not None and delay_seconds > 0:
                utime.sleep(delay_seconds)
                
            # 检查是否被取消
            if self.__status == self.Status.CANCELLED:
                return
                
            rv = self.__target(*self.__args, **self.__kwargs)
            
            with self.__lock:
                self.__status = self.Status.COMPLETED
                self.__result.set(rv=rv)
                
        except Exception as e:
            sys.print_exception(e)
            with self.__lock:
                self.__status = self.Status.FAILED
                self.__error = e
                self.__result.set(exc=e)
        finally:
            with self.__lock:
                self.__end_time = utime.ticks_ms()
            gc.collect()

    def cancel(self) -> bool:
        """取消任务
        
        Returns:
            bool: 是否成功取消
        """
        with self.__lock:
            if self.__status == self.Status.PENDING:
                self.__status = self.Status.CANCELLED
                return True
            elif self.__status == self.Status.RUNNING and self.__thread:
                self.__status = self.Status.CANCELLED
                self.__thread.terminate()
                return True
            return False

    @property
    def status(self) -> str:
        """返回任务状态"""
        return self.__status

    @property
    def error(self) -> Optional[Exception]:
        """返回任务错误信息"""
        return self.__error

    @property
    def execution_time(self) -> Optional[float]:
        """返回任务执行时间（毫秒）"""
        if self.__start_time is None:
            return None
        end_time = self.__end_time or utime.ticks_ms()
        return utime.ticks_diff(end_time, self.__start_time)

    @staticmethod
    def wrapper(func: Callable) -> Callable:
        """装饰器，用于创建异步任务
        
        Args:
            func: 要执行的函数
            
        Returns:
            Callable: 返回创建异步任务的函数
        """
        def inner_wrapper(*args, **kwargs):
            return AsyncTask(target=func, args=args, kwargs=kwargs)
        return inner_wrapper


class _WorkItem:
    """工作项封装类，用于在线程池中执行任务"""

    def __init__(self, target: Optional[Callable] = None, args: tuple = (), kwargs: Optional[dict] = None):
        self.__target = target
        self.__args = args
        self.__kwargs = kwargs or {}
        self.result = _Result()

    def __call__(self) -> None:
        try:
            rv = self.__target(*self.__args, **self.__kwargs)
        except Exception as e:
            self.result.set(exc=e)
        else:
            self.result.set(rv=rv)
        finally:
            gc.collect()  # 清理工作项资源


def _worker(work_queue: 'Queue') -> None:
    """工作线程函数
    
    Args:
        work_queue: 任务队列
    """
    while True:
        try:
            task = work_queue.get()
            if task is None:  # 关闭信号
                break
            task()
        except Exception as e:
            sys.print_exception(e)
        finally:
            gc.collect()  # 清理工作者线程资源


class ThreadPoolExecutor:
    """线程池执行器
    
    用于管理一组工作线程来执行提交的任务。
    """

    def __init__(self, max_workers: Optional[int] = None):
        """初始化线程池执行器
        
        Args:
            max_workers: 最大工作线程数，默认为None（CPU核心数 * 5）
        """
        if max_workers is None:
            try:
                max_workers = len(os.sched_getaffinity(0)) * 5
            except AttributeError:
                max_workers = os.cpu_count() * 5
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than 0")
            
        self.__max_workers = max_workers
        self.__work_queue: Queue = Queue()
        self.__threads: List[Thread] = []
        self.__shutdown = False
        self.__thread_name_prefix = "ThreadPool"
        
    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> _Result:
        """提交一个任务到线程池
        
        Args:
            fn: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            _Result: 任务结果对象
            
        Raises:
            RuntimeError: 线程池已关闭
        """
        if self.__shutdown:
            raise RuntimeError("cannot schedule new futures after shutdown")
            
        result = _Result()
        work = _WorkItem(fn, args, kwargs)
        self.__work_queue.put(work)
        
        self.__adjust_thread_count()
        return result
        
    def __adjust_thread_count(self) -> None:
        """调整工作线程数量"""
        if len(self.__threads) < self.__max_workers:
            thread_name = f"{self.__thread_name_prefix}-{len(self.__threads) + 1}"
            t = Thread(target=_worker, args=(self.__work_queue,), name=thread_name)
            t.daemon = True
            t.start()
            self.__threads.append(t)
            
    def shutdown(self, wait: bool = True) -> None:
        """关闭线程池
        
        Args:
            wait: 是否等待所有任务完成
        """
        self.__shutdown = True
        if wait:
            for _ in self.__threads:
                self.__work_queue.put(None)
            for t in self.__threads:
                t.join()

