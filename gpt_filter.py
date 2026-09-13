#!/usr/bin/env python3
"""
Минимальный standalone модуль для фильтрации username по полу через OpenAI GPT
Поддержка: async/sync, кастомизация промптов, батч-обработка

Использование:
    filter = GPTGenderFilter(api_key="your-openai-key")
    
    # Фильтрация женских username
    female_usernames = await filter.filter_female(usernames, count=30)
    
    # Фильтрация мужских username
    male_usernames = await filter.filter_male(usernames, count=20)
    
    # Кастомная фильтрация
    result = await filter.filter_custom(usernames, "tech enthusiasts", count=15)
"""

import os
import logging
import random
from typing import List, Optional, Dict, Any
from enum import Enum

try:
    from openai import AsyncOpenAI, OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    print("⚠️ openai не установлен. Установите: pip install openai")


# ============================================================================
# ENUMS
# ============================================================================

class Gender(str, Enum):
    """Пол для фильтрации"""
    FEMALE = "female"
    MALE = "male"
    BOTH = "both"


class GPTModel(str, Enum):
    """Поддерживаемые модели GPT"""
    GPT4O = "gpt-4o"
    GPT4O_MINI = "gpt-4o-mini"
    GPT35_TURBO = "gpt-3.5-turbo"


# ============================================================================
# GPT GENDER FILTER
# ============================================================================

class GPTGenderFilter:
    """
    Фильтр username по полу через OpenAI GPT
    
    Args:
        api_key: OpenAI API ключ (опционально, можно передать позже)
        model: Модель GPT (по умолчанию gpt-4o-mini)
        temperature: Температура генерации (0.0-1.0, по умолчанию 0.3)
        max_tokens: Максимум токенов в ответе (по умолчанию 1000)
        batch_size: Размер батча для обработки (по умолчанию 300)
        verbose: Вывод логов (по умолчанию True)
    """
    
    DEFAULT_PROMPTS = {
        Gender.FEMALE: """Analyze these Telegram usernames and identify which ones likely belong to FEMALE users.

Rules:
1. Look for feminine indicators: female names, feminine words, typical female username patterns
2. Return EXACTLY {count} usernames (or fewer if not enough female usernames found)
3. Return ONLY the usernames, one per line, without @ symbol
4. If a username is ambiguous, skip it
5. Prioritize confidence - only include usernames you're confident are female

Usernames to analyze:
{usernames}

Return format (just the usernames, nothing else):""",
        
        Gender.MALE: """Analyze these Telegram usernames and identify which ones likely belong to MALE users.

Rules:
1. Look for masculine indicators: male names, masculine words, typical male username patterns
2. Return EXACTLY {count} usernames (or fewer if not enough male usernames found)
3. Return ONLY the usernames, one per line, without @ symbol
4. If a username is ambiguous, skip it
5. Prioritize confidence - only include usernames you're confident are male

Usernames to analyze:
{usernames}

Return format (just the usernames, nothing else):"""
    }
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = GPTModel.GPT4O_MINI,
        temperature: float = 0.3,
        max_tokens: int = 1000,
        batch_size: int = 300,
        verbose: bool = True
    ):
        if not HAS_OPENAI:
            raise ImportError("openai не установлен. Установите: pip install openai")
        
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.batch_size = batch_size
        self.verbose = verbose
        
        # Клиенты (инициализируются при первом использовании)
        self._async_client: Optional[AsyncOpenAI] = None
        self._sync_client: Optional[OpenAI] = None
        
        # Логирование
        self.logger = logging.getLogger(__name__)
        if verbose:
            logging.basicConfig(level=logging.INFO)
    
    def set_api_key(self, api_key: str) -> None:
        """Установить OpenAI API ключ"""
        self.api_key = api_key.strip()
        # Сбрасываем клиентов для пересоздания с новым ключом
        self._async_client = None
        self._sync_client = None
        if self.verbose:
            self.logger.info("✅ OpenAI API ключ установлен")
    
    def check_api_key(self) -> bool:
        """Проверить наличие API ключа"""
        return bool(self.api_key)
    
    @property
    def async_client(self) -> AsyncOpenAI:
        """Получить async клиент (lazy initialization)"""
        if not self.api_key:
            raise ValueError("OpenAI API ключ не установлен")
        
        if self._async_client is None:
            self._async_client = AsyncOpenAI(api_key=self.api_key)
        
        return self._async_client
    
    @property
    def sync_client(self) -> OpenAI:
        """Получить sync клиент (lazy initialization)"""
        if not self.api_key:
            raise ValueError("OpenAI API ключ не установлен")
        
        if self._sync_client is None:
            self._sync_client = OpenAI(api_key=self.api_key)
        
        return self._sync_client
    
    def _prepare_usernames(self, usernames: List[str]) -> List[str]:
        """Подготовить username (убрать @, дедупликация)"""
        cleaned = [u.strip().lstrip('@') for u in usernames if u.strip()]
        # Дедупликация с сохранением порядка
        seen = set()
        return [u for u in cleaned if u.lower() not in seen and not seen.add(u.lower())]
    
    def _parse_response(self, response: str, original_usernames: List[str]) -> List[str]:
        """Парсинг ответа GPT и валидация"""
        # Извлекаем username из ответа
        filtered = [
            username.strip().lstrip('@')
            for username in response.split('\n')
            if username.strip()
        ]
        
        # Валидация: username должны быть из исходного списка
        original_set = {u.lower() for u in original_usernames}
        validated = [
            u for u in filtered
            if u.lower() in original_set
        ]
        
        return validated
    
    async def _filter_async(
        self,
        usernames: List[str],
        prompt_template: str,
        system_message: str,
        count: int
    ) -> List[str]:
        """Внутренняя async фильтрация"""
        if not usernames:
            if self.verbose:
                self.logger.warning("⚠️ Список usernames пуст")
            return []
        
        # Подготовка
        cleaned_usernames = self._prepare_usernames(usernames)
        
        # Батчирование
        if len(cleaned_usernames) > self.batch_size:
            if self.verbose:
                self.logger.info(f"📦 Батчирование: {len(cleaned_usernames)} → {self.batch_size}")
            cleaned_usernames = random.sample(cleaned_usernames, self.batch_size)
        
        # Формируем промпт
        prompt = prompt_template.format(
            count=count,
            usernames='\n'.join(cleaned_usernames)
        )
        
        try:
            if self.verbose:
                self.logger.info(f"🤖 Отправка запроса в GPT ({self.model})...")
            
            response = await self.async_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            result = response.choices[0].message.content.strip()
            
            # Парсим результат
            filtered_usernames = self._parse_response(result, cleaned_usernames)
            
            if self.verbose:
                self.logger.info(
                    f"✅ GPT отфильтровал {len(filtered_usernames)} username "
                    f"из {len(cleaned_usernames)}"
                )
            
            return filtered_usernames[:count]
        
        except Exception as e:
            self.logger.error(f"❌ Ошибка GPT фильтрации: {e}")
            return []
    
    def _filter_sync(
        self,
        usernames: List[str],
        prompt_template: str,
        system_message: str,
        count: int
    ) -> List[str]:
        """Внутренняя sync фильтрация"""
        if not usernames:
            if self.verbose:
                self.logger.warning("⚠️ Список usernames пуст")
            return []
        
        # Подготовка
        cleaned_usernames = self._prepare_usernames(usernames)
        
        # Батчирование
        if len(cleaned_usernames) > self.batch_size:
            if self.verbose:
                self.logger.info(f"📦 Батчирование: {len(cleaned_usernames)} → {self.batch_size}")
            cleaned_usernames = random.sample(cleaned_usernames, self.batch_size)
        
        # Формируем промпт
        prompt = prompt_template.format(
            count=count,
            usernames='\n'.join(cleaned_usernames)
        )
        
        try:
            if self.verbose:
                self.logger.info(f"🤖 Отправка запроса в GPT ({self.model})...")
            
            response = self.sync_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            result = response.choices[0].message.content.strip()
            
            # Парсим результат
            filtered_usernames = self._parse_response(result, cleaned_usernames)
            
            if self.verbose:
                self.logger.info(
                    f"✅ GPT отфильтровал {len(filtered_usernames)} username "
                    f"из {len(cleaned_usernames)}"
                )
            
            return filtered_usernames[:count]
        
        except Exception as e:
            self.logger.error(f"❌ Ошибка GPT фильтрации: {e}")
            return []
    
    # ========================================================================
    # PUBLIC ASYNC API
    # ========================================================================
    
    async def filter_female(self, usernames: List[str], count: int = 30) -> List[str]:
        """
        Фильтрация женских username (async)
        
        Args:
            usernames: Список username
            count: Количество результатов
        
        Returns:
            Список женских username
        """
        return await self._filter_async(
            usernames=usernames,
            prompt_template=self.DEFAULT_PROMPTS[Gender.FEMALE],
            system_message="You are an expert at identifying gender from usernames. Be conservative - only return usernames you're confident are female.",
            count=count
        )
    
    async def filter_male(self, usernames: List[str], count: int = 30) -> List[str]:
        """
        Фильтрация мужских username (async)
        
        Args:
            usernames: Список username
            count: Количество результатов
        
        Returns:
            Список мужских username
        """
        return await self._filter_async(
            usernames=usernames,
            prompt_template=self.DEFAULT_PROMPTS[Gender.MALE],
            system_message="You are an expert at identifying gender from usernames. Be conservative - only return usernames you're confident are male.",
            count=count
        )
    
    async def filter_custom(
        self,
        usernames: List[str],
        criteria: str,
        count: int = 30,
        system_message: Optional[str] = None
    ) -> List[str]:
        """
        Кастомная фильтрация username (async)
        
        Args:
            usernames: Список username
            criteria: Критерии фильтрации (например, "crypto enthusiasts")
            count: Количество результатов
            system_message: Опциональное системное сообщение
        
        Returns:
            Отфильтрованные username
        """
        prompt_template = f"""Analyze these Telegram usernames and identify which ones likely belong to: {criteria}

Rules:
1. Look for relevant indicators and patterns
2. Return EXACTLY {{count}} usernames (or fewer if not enough found)
3. Return ONLY the usernames, one per line, without @ symbol
4. If a username is ambiguous, skip it
5. Prioritize confidence

Usernames to analyze:
{{usernames}}

Return format (just the usernames, nothing else):"""
        
        default_system = f"You are an expert at analyzing usernames to identify {criteria}."
        
        return await self._filter_async(
            usernames=usernames,
            prompt_template=prompt_template,
            system_message=system_message or default_system,
            count=count
        )
    
    # ========================================================================
    # PUBLIC SYNC API
    # ========================================================================
    
    def filter_female_sync(self, usernames: List[str], count: int = 30) -> List[str]:
        """Фильтрация женских username (sync)"""
        return self._filter_sync(
            usernames=usernames,
            prompt_template=self.DEFAULT_PROMPTS[Gender.FEMALE],
            system_message="You are an expert at identifying gender from usernames. Be conservative - only return usernames you're confident are female.",
            count=count
        )
    
    def filter_male_sync(self, usernames: List[str], count: int = 30) -> List[str]:
        """Фильтрация мужских username (sync)"""
        return self._filter_sync(
            usernames=usernames,
            prompt_template=self.DEFAULT_PROMPTS[Gender.MALE],
            system_message="You are an expert at identifying gender from usernames. Be conservative - only return usernames you're confident are male.",
            count=count
        )
    
    def filter_custom_sync(
        self,
        usernames: List[str],
        criteria: str,
        count: int = 30,
        system_message: Optional[str] = None
    ) -> List[str]:
        """Кастомная фильтрация username (sync)"""
        prompt_template = f"""Analyze these Telegram usernames and identify which ones likely belong to: {criteria}

Rules:
1. Look for relevant indicators and patterns
2. Return EXACTLY {{count}} usernames (or fewer if not enough found)
3. Return ONLY the usernames, one per line, without @ symbol
4. If a username is ambiguous, skip it
5. Prioritize confidence

Usernames to analyze:
{{usernames}}

Return format (just the usernames, nothing else):"""
        
        default_system = f"You are an expert at analyzing usernames to identify {criteria}."
        
        return self._filter_sync(
            usernames=usernames,
            prompt_template=prompt_template,
            system_message=system_message or default_system,
            count=count
        )


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def filter_female_usernames(
    usernames: List[str],
    count: int = 30,
    api_key: Optional[str] = None,
    **kwargs
) -> List[str]:
    """
    Быстрая функция для фильтрации женских username
    
    Args:
        usernames: Список username
        count: Количество результатов
        api_key: OpenAI API ключ
        **kwargs: Дополнительные параметры для GPTGenderFilter
    
    Returns:
        Список женских username
    """
    filter_instance = GPTGenderFilter(api_key=api_key, **kwargs)
    return await filter_instance.filter_female(usernames, count)


async def filter_male_usernames(
    usernames: List[str],
    count: int = 30,
    api_key: Optional[str] = None,
    **kwargs
) -> List[str]:
    """
    Быстрая функция для фильтрации мужских username
    
    Args:
        usernames: Список username
        count: Количество результатов
        api_key: OpenAI API ключ
        **kwargs: Дополнительные параметры для GPTGenderFilter
    
    Returns:
        Список мужских username
    """
    filter_instance = GPTGenderFilter(api_key=api_key, **kwargs)
    return await filter_instance.filter_male(usernames, count)


# ============================================================================
# EXAMPLE
# ============================================================================

async def main():
    """Примеры использования"""
    import asyncio
    
    # Тестовые данные
    test_usernames = [
        "anna_smith", "john_doe", "maria_garcia", "michael_brown",
        "elena_peterson", "david_wilson", "sophia_moore", "james_taylor",
        "natasha_russian", "robert_jones", "victoria_secret", "william_clark"
    ]
    
    print("=" * 80)
    print("🤖 GPT GENDER FILTER - DEMO")
    print("=" * 80)
    
    # Инициализация (используйте свой API ключ)
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("\n❌ Установите OPENAI_API_KEY в переменных окружения")
        return
    
    filter_instance = GPTGenderFilter(
        api_key=api_key,
        model=GPTModel.GPT4O_MINI,
        verbose=True
    )
    
    # Пример 1: Фильтрация женских username
    print("\n1️⃣ Фильтрация женских username:")
    female_usernames = await filter_instance.filter_female(test_usernames, count=5)
    print(f"Результат: {female_usernames}")
    
    # Пример 2: Фильтрация мужских username
    print("\n2️⃣ Фильтрация мужских username:")
    male_usernames = await filter_instance.filter_male(test_usernames, count=5)
    print(f"Результат: {male_usernames}")
    
    # Пример 3: Кастомная фильтрация
    print("\n3️⃣ Кастомная фильтрация (tech names):")
    tech_names = await filter_instance.filter_custom(
        test_usernames,
        criteria="people interested in technology",
        count=3
    )
    print(f"Результат: {tech_names}")
    
    # Пример 4: Использование convenience функции
    print("\n4️⃣ Использование convenience функции:")
    females = await filter_female_usernames(test_usernames, count=3, api_key=api_key)
    print(f"Результат: {females}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())