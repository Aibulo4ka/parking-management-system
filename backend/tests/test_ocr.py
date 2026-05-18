"""
Тесты для эндпоинтов OCR (распознавание номерных знаков)
"""
import pytest
from httpx import AsyncClient
from io import BytesIO
from PIL import Image


@pytest.mark.asyncio
async def test_validate_license_plate_valid(client: AsyncClient):
    """Тест валидации корректного российского номера"""
    response = await client.post(
        "/api/ocr/validate",
        params={"license_plate": "А123ВС77"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is True
    assert data["format"] == "Russian standard"


@pytest.mark.asyncio
async def test_validate_license_plate_valid_3digit_region(client: AsyncClient):
    """Тест валидации номера с трехзначным регионом"""
    response = await client.post(
        "/api/ocr/validate",
        params={"license_plate": "М123КУ777"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is True


@pytest.mark.asyncio
async def test_validate_license_plate_invalid(client: AsyncClient):
    """Тест валидации некорректного номера"""
    response = await client.post(
        "/api/ocr/validate",
        params={"license_plate": "123ABC"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is False
    assert data["format"] == "Unknown/Invalid"


@pytest.mark.asyncio
async def test_validate_license_plate_lowercase(client: AsyncClient):
    """Тест валидации номера в нижнем регистре"""
    response = await client.post(
        "/api/ocr/validate",
        params={"license_plate": "а123вс77"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is True
    assert data["license_plate"] == "А123ВС77"  # Должен быть преобразован в верхний регистр


@pytest.mark.asyncio
async def test_recognize_invalid_file_type(client: AsyncClient):
    """Тест загрузки файла неподдерживаемого типа"""
    # Создаем текстовый файл
    text_file = BytesIO(b"This is not an image")

    response = await client.post(
        "/api/ocr/recognize",
        files={"file": ("test.txt", text_file, "text/plain")}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_recognize_file_too_large(client: AsyncClient):
    """Тест загрузки слишком большого файла"""
    # Создаем файл больше 10MB
    large_data = b"x" * (11 * 1024 * 1024)  # 11 MB

    response = await client.post(
        "/api/ocr/recognize",
        files={"file": ("large.jpg", BytesIO(large_data), "image/jpeg")}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_recognize_valid_image_format(client: AsyncClient):
    """Тест загрузки изображения поддерживаемого формата"""
    # Создаем простое тестовое изображение
    img = Image.new('RGB', (100, 50), color='white')
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    response = await client.post(
        "/api/ocr/recognize",
        files={"file": ("test.png", img_bytes, "image/png")}
    )

    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "license_plate" in data
    # Так как это пустое изображение, распознавание может не удаться
    # но ответ должен быть корректным


@pytest.mark.asyncio
async def test_recognize_jpeg_format(client: AsyncClient):
    """Тест загрузки JPEG изображения"""
    img = Image.new('RGB', (200, 100), color='blue')
    img_bytes = BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)

    response = await client.post(
        "/api/ocr/recognize",
        files={"file": ("test.jpg", img_bytes, "image/jpeg")}
    )

    assert response.status_code == 200
    data = response.json()
    assert "success" in data


def test_preprocess_license_plate_text():
    """Тест предобработки текста номера"""
    from app.utils.ocr import preprocess_license_plate_text

    # Примечание: функция удаляет не-ASCII символы, поэтому русские буквы удаляются
    # Это поведение OCR функции - она работает с латинскими буквами

    # Тест с пробелами - остаются только цифры и латинские буквы
    result = preprocess_license_plate_text("A 123 BC 77")
    assert result == "A123BC77"

    # Тест с нижним регистром
    result = preprocess_license_plate_text("a123bc77")
    assert result == "A123BC77"

    # Тест со специальными символами
    result = preprocess_license_plate_text("A-123-BC-77")
    assert result == "A123BC77"

    # Тест с пробелами в начале и конце
    result = preprocess_license_plate_text("  A123BC77  ")
    assert result == "A123BC77"


def test_validate_russian_license_plate():
    """Тест валидации российских номерных знаков"""
    from app.utils.ocr import validate_russian_license_plate

    # Валидные номера (только разрешённые ГИБДД буквы: А В Е К М Н О Р С Т У Х)
    assert validate_russian_license_plate("А123ВС77") is True
    assert validate_russian_license_plate("М999КУ777") is True
    assert validate_russian_license_plate("С001РС199") is True
    assert validate_russian_license_plate("Т456ЕС777") is True

    # Невалидные номера
    assert validate_russian_license_plate("123ABC") is False
    assert validate_russian_license_plate("A123BC77") is False  # Латинские буквы
    assert validate_russian_license_plate("АБ123ВГ77") is False  # Неправильный порядок + Б/Г запрещены
    assert validate_russian_license_plate("А12ВС77") is False  # Недостаточно цифр
    assert validate_russian_license_plate("А1234ВС77") is False  # Слишком много цифр
    assert validate_russian_license_plate("") is False
    assert validate_russian_license_plate("А123ВС") is False  # Нет региона


def test_format_license_plate():
    """Тест форматирования номерных знаков"""
    from app.utils.ocr import format_license_plate

    # Стандартный формат с русскими буквами
    result = format_license_plate("А123БВ77")
    assert result == "А123БВ77"

    # С нижним регистром
    result = format_license_plate("а123бв77")
    assert result == "А123БВ77"

    # С трехзначным регионом
    result = format_license_plate("М999КУ777")
    assert result == "М999КУ777"

    # Номер без форматирования
    result = format_license_plate("С001РС199")
    assert result == "С001РС199"


def test_valid_russian_letters_only():
    """Тест что используются только разрешенные русские буквы в номерах"""
    from app.utils.ocr import validate_russian_license_plate

    # Разрешенные буквы: А, В, Е, К, М, Н, О, Р, С, Т, У, Х
    valid_letters = "АВЕКМНОРСТУХ"

    # Проверяем, что номера с разрешенными буквами валидны
    for letter in valid_letters:
        assert validate_russian_license_plate(f"{letter}123{valid_letters[0]}{valid_letters[1]}77") is True

    # Проверяем, что номера с недопустимыми русскими буквами невалидны
    invalid_letters = "БГДЖЗИЙЛПФЦЧШЩЪЫЬЭЮЯ"
    for letter in invalid_letters:
        assert validate_russian_license_plate(f"{letter}123АВ77") is False


@pytest.mark.asyncio
async def test_multiple_validate_requests(client: AsyncClient):
    """Тест множественных запросов валидации"""
    test_plates = [
        ("А123ВС77", True),
        ("М456КУ99", True),
        ("invalid", False),
        ("С777РС777", True),
        ("12345", False)
    ]

    for plate, expected_valid in test_plates:
        response = await client.post(
            "/api/ocr/validate",
            params={"license_plate": plate}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] == expected_valid


@pytest.mark.asyncio
async def test_recognize_empty_image(client: AsyncClient):
    """Тест распознавания на пустом изображении"""
    # Создаем чистое белое изображение без текста
    img = Image.new('RGB', (300, 150), color='white')
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    response = await client.post(
        "/api/ocr/recognize",
        files={"file": ("empty.png", img_bytes, "image/png")}
    )

    assert response.status_code == 200
    data = response.json()
    # На пустом изображении распознавание должно вернуть success: false
    # или license_plate: None
    assert "success" in data
    if not data["success"]:
        assert data["license_plate"] is None


@pytest.mark.asyncio
async def test_recognize_missing_file(client: AsyncClient):
    """Тест запроса без файла"""
    response = await client.post("/api/ocr/recognize")

    assert response.status_code == 422  # Validation error


def test_ocr_utils_edge_cases():
    """Тест граничных случаев для утилит OCR"""
    from app.utils.ocr import preprocess_license_plate_text, format_license_plate

    # Пустая строка
    assert preprocess_license_plate_text("") == ""

    # Только пробелы
    assert preprocess_license_plate_text("   ") == ""

    # Только специальные символы
    assert preprocess_license_plate_text("---///***") == ""

    # Латинские буквы и цифры
    assert preprocess_license_plate_text("A123BC77") == "A123BC77"

    # Очень длинные строки фильтруются как «не номер» — возвращается пусто
    long_text = "A" * 100
    result = preprocess_license_plate_text(long_text)
    assert result == ""

    # Форматирование пустой строки
    assert format_license_plate("") == ""
