# ============================================================
#  connector.py — Коннектор к 1С:Fresh через OData REST API
# ============================================================
import requests
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

# Ставки НДС в 1С (актуально с 2025 года: основная ставка 22%)
НДС_СТАВКИ = {
    22:  "НДС22",    # основная с 2025
    20:  "НДС20",    # была до 2025
    10:  "НДС10",    # льготная
    0:   "НДС0",     # экспорт
    None:"БезНДС",   # без НДС
}
НДС_ПО_УМОЛЧАНИЮ = "НДС22"


class Fresh1CError(Exception):
    pass


class Fresh1C:
    def __init__(self, base_url: str, username: str, password: str,
                 verify_ssl: bool = True, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.odata_url = f"{self.base_url}/odata/standard.odata"
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        credentials = f"{username}:{password}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        self.headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json;odata=verbose",
            "Accept": "application/json",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.verify = self.verify_ssl

    # ── БАЗОВЫЕ HTTP МЕТОДЫ ────────────────────────────────────

    def _get(self, resource: str, params: Dict = None) -> Any:
        url = f"{self.odata_url}/{resource}"
        p = {"$format": "json"}
        if params:
            p.update(params)
        try:
            r = self.session.get(url, params=p, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data.get("value", data)
        except requests.HTTPError as e:
            raise Fresh1CError(f"HTTP {e.response.status_code}: {e.response.text[:300]}")
        except requests.ConnectionError:
            raise Fresh1CError(f"Нет подключения к {url}")
        except Exception as e:
            raise Fresh1CError(f"Ошибка: {e}")

    def _post(self, resource: str, data: Dict = None) -> Any:
        url = f"{self.odata_url}/{resource}"
        try:
            r = self.session.post(url, params={"$format": "json"},
                                  json=data or {}, timeout=self.timeout)
            r.raise_for_status()
            return r.json() if r.text else {"status": "ok"}
        except requests.HTTPError as e:
            raise Fresh1CError(f"HTTP {e.response.status_code}: {e.response.text[:300]}")
        except Exception as e:
            raise Fresh1CError(f"Ошибка POST: {e}")

    def _patch(self, resource: str, data: Dict) -> bool:
        url = f"{self.odata_url}/{resource}"
        try:
            r = self.session.patch(url, params={"$format": "json"},
                                   json=data, timeout=self.timeout)
            r.raise_for_status()
            return True
        except requests.HTTPError as e:
            raise Fresh1CError(f"HTTP {e.response.status_code}: {e.response.text[:300]}")
        except Exception as e:
            raise Fresh1CError(f"Ошибка PATCH: {e}")

    def _delete(self, resource: str) -> bool:
        """Физическое удаление через DELETE + If-Match: DataVersion."""
        url = f"{self.odata_url}/{resource}"
        # 1. Получаем DataVersion
        try:
            r = self.session.get(url, params={"$format": "json", "$select": "DataVersion"},
                                 timeout=self.timeout)
            r.raise_for_status()
            data_version = r.json().get("DataVersion", "")
        except requests.HTTPError as e:
            raise Fresh1CError(f"GET перед DELETE: HTTP {e.response.status_code}: {e.response.text[:200]}")
        except Exception as e:
            raise Fresh1CError(f"GET перед DELETE: {e}")
        # 2. DELETE с заголовком If-Match
        try:
            headers = {"If-Match": data_version} if data_version else {}
            r = self.session.delete(url, params={"$format": "json"},
                                    headers=headers, timeout=self.timeout)
            r.raise_for_status()
            return True
        except requests.HTTPError as e:
            raise Fresh1CError(f"DELETE HTTP {e.response.status_code}: {e.response.text[:300]}")
        except Exception as e:
            raise Fresh1CError(f"Ошибка DELETE: {e}")

    # ── ПРОВЕРКА ПОДКЛЮЧЕНИЯ ───────────────────────────────────

    def check_connection(self) -> bool:
        try:
            self._get("Catalog_Организации", {"$top": "1"})
            print("✅ Подключение к 1С:Fresh успешно!")
            return True
        except Fresh1CError as e:
            print(f"❌ Ошибка подключения: {e}")
            return False

    # ── КОНТРАГЕНТЫ ────────────────────────────────────────────

    # OData 1С:Fresh не поддерживает contains() и не разрешает $filter по ИНН.
    # Поэтому search и поиск по ИНН делаем клиентской фильтрацией поверх пагинации.
    _CTR_SELECT = (
        "Ref_Key,Code,Description,НаименованиеПолное,ИНН,КПП,"
        "ЮридическоеФизическоеЛицо,Комментарий"
    )
    _PAGE_SIZE = 500

    def get_counterparties(self, top: int = 100, filter: str = None,
                           search: str = None) -> List[Dict]:
        """
        Получить контрагентов. Если search задан — листаем страницами и
        фильтруем по подстроке (case-insensitive) в Description / НаименованиеПолное.
        """
        if not search:
            params = {"$top": str(top), "$select": self._CTR_SELECT}
            if filter:
                params["$filter"] = filter
            result = self._get("Catalog_Контрагенты", params)
            print(f"📋 Контрагентов: {len(result)}")
            return result

        needle = search.casefold()
        matches: List[Dict] = []
        skip = 0
        while len(matches) < top:
            params = {
                "$top": str(self._PAGE_SIZE),
                "$skip": str(skip),
                "$select": self._CTR_SELECT,
            }
            if filter:
                params["$filter"] = filter
            page = self._get("Catalog_Контрагенты", params)
            if not page:
                break
            for row in page:
                descr = (row.get("Description") or "").casefold()
                full = (row.get("НаименованиеПолное") or "").casefold()
                if needle in descr or needle in full:
                    matches.append(row)
                    if len(matches) >= top:
                        break
            if len(page) < self._PAGE_SIZE:
                break
            skip += self._PAGE_SIZE
        print(f"📋 Найдено контрагентов: {len(matches)} (поиск '{search}')")
        return matches

    def get_counterparty_by_inn(self, inn: str) -> Optional[Dict]:
        """
        Точный поиск по ИНН. Серверный $filter по ИНН запрещён, поэтому
        листаем страницами с минимальной выборкой и сравниваем клиентом,
        затем тянем полную карточку по найденному GUID.
        """
        target = (inn or "").strip()
        if not target:
            return None
        skip = 0
        found_ref: Optional[str] = None
        while True:
            page = self._get("Catalog_Контрагенты", {
                "$top": str(self._PAGE_SIZE),
                "$skip": str(skip),
                "$select": "Ref_Key,ИНН",
            })
            if not page:
                break
            for row in page:
                if (row.get("ИНН") or "").strip() == target:
                    found_ref = row["Ref_Key"]
                    break
            if found_ref or len(page) < self._PAGE_SIZE:
                break
            skip += self._PAGE_SIZE
        if not found_ref:
            return None
        return self._get(
            f"Catalog_Контрагенты(guid'{found_ref}')",
            {"$select": self._CTR_SELECT},
        )

    def create_counterparty(self, name: str, inn: str = "", kpp: str = "",
                            full_name: str = "", comment: str = "",
                            is_legal: bool = True) -> Dict:
        """Создать контрагента. is_legal=True → ЮрЛицо, False → ФизЛицо"""
        data = {
            "Description": name,
            "НаименованиеПолное": full_name or name,
            "ИНН": inn,
            "КПП": kpp,
            "Комментарий": comment,
            "ЮридическоеФизическоеЛицо": "ЮридическоеЛицо" if is_legal else "ФизическоеЛицо",
        }
        result = self._post("Catalog_Контрагенты", data)
        print(f"✅ Контрагент создан: {name} (ИНН: {inn})")
        return result

    # ── СЧЕТА НА ОПЛАТУ ────────────────────────────────────────

    def get_invoices(self, top: int = 100, date_from: str = None,
                     date_to: str = None, filter: str = None) -> List[Dict]:
        """Поля: Date, Posted (не Дата/Проведен!)"""
        params = {
            "$top": str(top),
            "$orderby": "Date desc",
            "$select": "Ref_Key,Number,Date,Организация_Key,Контрагент_Key,СуммаДокумента,Posted,Комментарий",
        }
        filters = []
        if date_from:
            filters.append(f"Date ge datetime'{date_from}'")
        if date_to:
            filters.append(f"Date le datetime'{date_to}'")
        if filter:
            filters.append(filter)
        if filters:
            params["$filter"] = " and ".join(filters)
        result = self._get("Document_СчетНаОплатуПокупателю", params)
        print(f"🧾 Счетов: {len(result)}")
        return result

    @staticmethod
    def make_item(nom_guid: str, qty: float, price: float,
                  description: str = "", nds: str = НДС_ПО_УМОЛЧАНИЮ,
                  line_num: int = 1) -> Dict:
        """
        Создать строку товара для счёта/реализации.
        nds: "НДС22" (по умолчанию), "НДС10", "НДС0", "БезНДС"
        """
        сумма = qty * price
        # Вычислить сумму НДС из ставки
        ставка = {"НДС22": 0.22, "НДС20": 0.20, "НДС10": 0.10, "НДС0": 0.0, "БезНДС": 0.0}
        сумма_ндс = round(сумма * ставка.get(nds, 0.22) / (1 + ставка.get(nds, 0.22)), 2)
        return {
            "LineNumber": str(line_num),
            "Номенклатура": nom_guid,
            "Номенклатура_Type": "StandardODATA.Catalog_Номенклатура",
            "Содержание": description,
            "Количество": qty,
            "Цена": price,
            "Сумма": сумма,
            "ПроцентСкидки": 0,
            "СуммаСкидки": 0,
            "СтавкаНДС": nds,          # ← НДС22 по умолчанию (с 2025 года)
            "СуммаНДС": сумма_ндс,
        }

    def create_invoice(self, counterparty_guid: str, items: List[Dict],
                       org_guid: str = None, comment: str = "",
                       includes_vat: bool = True) -> Dict:
        """
        Создать счёт на оплату покупателю.
        items — строки через make_item() (НДС22 по умолчанию).
        """
        # Проставляем LineNumber если не указан
        for i, item in enumerate(items, 1):
            item.setdefault("LineNumber", str(i))

        data = {
            "Date": Fresh1C.format_date(),        # текущее время НСК (UTC+7)
            "Контрагент_Key": counterparty_guid,
            "Комментарий": comment,
            "СуммаВключаетНДС": includes_vat,
            "Товары": items,
        }
        if org_guid:
            data["Организация_Key"] = org_guid
        result = self._post("Document_СчетНаОплатуПокупателю", data)
        print(f"✅ Счёт создан: №{result.get('Number','?')} на {result.get('СуммаДокумента',0):,.0f} ₽")
        return result

    # ── РЕАЛИЗАЦИЯ ─────────────────────────────────────────────

    def get_sales(self, top: int = 100, date_from: str = None,
                  date_to: str = None) -> List[Dict]:
        """Реализации товаров и услуг — основной документ продажи"""
        params = {
            "$top": str(top),
            "$orderby": "Date desc",
            "$select": "Ref_Key,Number,Date,Организация_Key,Контрагент_Key,СуммаДокумента,Posted,Комментарий",
        }
        filters = []
        if date_from:
            filters.append(f"Date ge datetime'{date_from}'")
        if date_to:
            filters.append(f"Date le datetime'{date_to}'")
        if filters:
            params["$filter"] = " and ".join(filters)
        result = self._get("Document_РеализацияТоваровУслуг", params)
        print(f"📋 Реализаций: {len(result)}")
        return result

    def get_orders(self, top: int = 100, date_from: str = None,
                   date_to: str = None) -> List[Dict]:
        return self.get_sales(top=top, date_from=date_from, date_to=date_to)

    # ── НОМЕНКЛАТУРА ────────────────────────────────────────────

    _PROD_SELECT = "Ref_Key,Code,Description,ЕдиницаИзмерения_Key,ВидНоменклатуры"

    def get_products(self, top: int = 200, search: str = None) -> List[Dict]:
        """
        Список номенклатуры. Поиск (search) — клиентская фильтрация по Description,
        т.к. 1С:Fresh OData не поддерживает contains().
        """
        if not search:
            result = self._get("Catalog_Номенклатура",
                               {"$top": str(top), "$select": self._PROD_SELECT})
            print(f"📦 Номенклатуры: {len(result)}")
            return result

        needle = search.casefold()
        matches: List[Dict] = []
        skip = 0
        while len(matches) < top:
            page = self._get("Catalog_Номенклатура", {
                "$top": str(self._PAGE_SIZE),
                "$skip": str(skip),
                "$select": self._PROD_SELECT,
            })
            if not page:
                break
            for row in page:
                if needle in (row.get("Description") or "").casefold():
                    matches.append(row)
                    if len(matches) >= top:
                        break
            if len(page) < self._PAGE_SIZE:
                break
            skip += self._PAGE_SIZE
        print(f"📦 Найдено номенклатуры: {len(matches)} (поиск '{search}')")
        return matches

    # ── ПОСТУПЛЕНИЯ ─────────────────────────────────────────────

    def get_payments(self, top: int = 100, date_from: str = None) -> List[Dict]:
        params = {
            "$top": str(top),
            "$orderby": "Date desc",
            "$select": "Ref_Key,Number,Date,Контрагент_Key,СуммаДокумента,Posted,Комментарий",
        }
        if date_from:
            params["$filter"] = f"Date ge datetime'{date_from}'"
        result = self._get("Document_ПоступлениеНаРасчетныйСчет", params)
        print(f"💰 Платежей: {len(result)}")
        return result

    # ── ОРГАНИЗАЦИИ ─────────────────────────────────────────────

    def get_organizations(self) -> List[Dict]:
        return self._get("Catalog_Организации",
                         {"$select": "Ref_Key,Code,Description,ИНН,КПП"})

    # ── ПРОВЕДЕНИЕ ──────────────────────────────────────────────

    def post_document(self, doc_type: str, guid: str) -> bool:
        self._post(f"Document_{doc_type}(guid'{guid}')/Post()")
        print(f"✅ {doc_type} проведён")
        return True

    def unpost_document(self, doc_type: str, guid: str) -> bool:
        self._post(f"Document_{doc_type}(guid'{guid}')/Unpost()")
        return True

    # ── УТИЛИТЫ ─────────────────────────────────────────────────

    # Часовой пояс — Новосибирск (UTC+7)
    NSK_TZ = timezone(timedelta(hours=7))

    @staticmethod
    def now_nsk() -> datetime:
        """Текущее время по Новосибирску (UTC+7)."""
        return datetime.now(tz=Fresh1C.NSK_TZ)

    @staticmethod
    def format_date(dt: datetime = None) -> str:
        """Форматирует дату для 1С OData. Если не передана — берёт текущее NSK-время."""
        if dt is None:
            dt = Fresh1C.now_nsk()
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def parse_date(odata_date: str) -> Optional[datetime]:
        if not odata_date:
            return None
        if odata_date.startswith("/Date("):
            return datetime.fromtimestamp(int(odata_date[6:-2]) / 1000)
        try:
            return datetime.fromisoformat(odata_date.replace("Z", "+00:00"))
        except Exception:
            return None
