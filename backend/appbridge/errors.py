"""Error codes and translation of common ADB / package-manager failures.

Every failure surfaced to the UI carries a stable ``code`` plus the raw ``detail`` text. The
UI shows the human message and a suggested fix in Arabic or English from :data:`MESSAGES`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class AppBridgeError(Exception):
    def __init__(self, code: str, detail: str = "", **params):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.params = params

    def to_dict(self) -> dict:
        return describe(self.code, self.detail, **self.params)


class DeviceGoneError(AppBridgeError):
    """The device disconnected or went offline during an operation."""

    def __init__(self, detail: str = ""):
        super().__init__("DEVICE_DISCONNECTED", detail)


class CancelledError(AppBridgeError):
    def __init__(self):
        super().__init__("CANCELLED")


@dataclass(frozen=True)
class Message:
    en: str
    ar: str
    hint_en: str = ""
    hint_ar: str = ""


MESSAGES: dict[str, Message] = {
    "UNKNOWN": Message(
        "An unexpected error occurred.",
        "حدث خطأ غير متوقع.",
        "Export the logs from Settings and check the details.",
        "صدّر السجلات من الإعدادات وراجع التفاصيل.",
    ),
    "CANCELLED": Message("The operation was cancelled.", "تم إلغاء العملية."),
    "ADB_NOT_FOUND": Message(
        "ADB (platform-tools) was not found.",
        "لم يتم العثور على ADB (platform-tools).",
        "Reinstall AppBridge; platform-tools ships inside the app.",
        "أعد تثبيت AppBridge؛ أدوات platform-tools مضمّنة داخل التطبيق.",
    ),
    "ADB_TIMEOUT": Message(
        "ADB did not respond in time.",
        "لم يستجب ADB في الوقت المحدد.",
        "Reconnect the cable and try again. Avoid loose USB hubs.",
        "أعد توصيل الكابل وحاول مرة أخرى، وتجنب موزعات USB غير الثابتة.",
    ),
    "DEVICE_UNAUTHORIZED": Message(
        "The phone has not authorized this computer.",
        "الهاتف لم يمنح التصريح لهذا الحاسوب.",
        "Unlock the phone and tap 'Allow' on the USB debugging prompt (tick 'Always allow').",
        "افتح قفل الهاتف واضغط «سماح» في نافذة تصحيح USB (وفعّل «السماح دائمًا»).",
    ),
    "DEVICE_OFFLINE": Message(
        "The device is offline.",
        "الجهاز غير متصل (offline).",
        "Unplug and reconnect the cable, or toggle USB debugging off and on.",
        "افصل الكابل وأعد توصيله، أو أوقف تصحيح USB ثم فعّله من جديد.",
    ),
    "DEVICE_NOT_FOUND": Message(
        "The device was not found.",
        "لم يتم العثور على الجهاز.",
        "Check the cable and that USB debugging is enabled.",
        "تحقق من الكابل ومن تفعيل تصحيح USB.",
    ),
    "DEVICE_DISCONNECTED": Message(
        "The device was disconnected during the operation.",
        "انفصل الجهاز أثناء العملية.",
        "Reconnect the cable; the task resumes without re-copying finished files.",
        "أعد توصيل الكابل؛ ستُستأنف المهمة دون إعادة نسخ الملفات المكتملة.",
    ),
    "PACKAGE_NOT_FOUND": Message(
        "The app is not installed on this phone.",
        "التطبيق غير مثبت على هذا الهاتف.",
        "Refresh the app list and pick the app again.",
        "حدّث قائمة التطبيقات واختر التطبيق مجددًا.",
    ),
    "DATA_ACCESS_DENIED": Message(
        "Android blocked reading Android/data for this app.",
        "منع أندرويد قراءة مجلد Android/data لهذا التطبيق.",
        "Some Android 14 phones block this folder over ADB. You can continue without it; "
        "the game will download its resources again on first launch.",
        "بعض هواتف أندرويد 14 تمنع هذا المجلد عبر ADB. يمكنك المتابعة بدونه، "
        "وستنزّل اللعبة مواردها من جديد عند أول تشغيل.",
    ),
    "DATA_WRITE_DENIED": Message(
        "The phone refused writing to Android/data.",
        "رفض الهاتف الكتابة في Android/data.",
        "Open the app once on the phone, close it, then retry the task.",
        "افتح التطبيق مرة واحدة على الهاتف ثم أغلقه، وأعد المحاولة.",
    ),
    "PERMISSION_DENIED": Message(
        "The phone denied access to a file or folder.",
        "رفض الهاتف الوصول إلى ملف أو مجلد.",
        "Unlock the phone and retry. Some folders are protected by Android and cannot be copied.",
        "افتح قفل الهاتف وأعد المحاولة. بعض المجلدات محمية من أندرويد ولا يمكن نسخها.",
    ),
    "PC_DISK_FULL": Message(
        "Not enough free space on this computer.",
        "لا توجد مساحة كافية على هذا الحاسوب.",
        "Free up space or choose another library folder in Settings.",
        "حرّر مساحة أو اختر مجلد مكتبة آخر من الإعدادات.",
    ),
    "DEVICE_STORAGE_FULL": Message(
        "Not enough free space on the phone.",
        "لا توجد مساحة كافية على الهاتف.",
        "Delete files or apps on the phone, then retry.",
        "احذف بعض الملفات أو التطبيقات من الهاتف ثم أعد المحاولة.",
    ),
    "LIBRARY_ITEM_INCOMPLETE": Message(
        "This library item is incomplete.",
        "عنصر المكتبة هذا غير مكتمل.",
        "Resume or redo the extraction from the source phone.",
        "استأنف الاستخراج أو أعده من الهاتف المصدر.",
    ),
    "HASH_MISMATCH": Message(
        "Some files are corrupted (SHA-256 mismatch).",
        "بعض الملفات تالفة (بصمة SHA-256 غير مطابقة).",
        "Extract the app again or re-import the bundle.",
        "أعد استخراج التطبيق أو أعد استيراد الحزمة.",
    ),
    "FILE_MISSING": Message(
        "Some files listed in the manifest are missing.",
        "بعض الملفات المذكورة في المانيفست مفقودة.",
        "Extract the app again or re-import the bundle.",
        "أعد استخراج التطبيق أو أعد استيراد الحزمة.",
    ),
    "SIGNATURE_MISMATCH": Message(
        "The app is signed with a different certificate than the installed one.",
        "التطبيق موقّع بشهادة مختلفة عن النسخة المثبتة.",
        "Uninstall the existing app first (its local data will be lost), then install.",
        "أزل التطبيق الموجود أولًا (ستُفقد بياناته المحلية) ثم ثبّت.",
    ),
    "SPLIT_SIGNATURE_MISMATCH": Message(
        "The split APK files are not signed with the same certificate.",
        "ملفات split APK غير موقّعة بنفس الشهادة.",
        "The copy is inconsistent; extract the app again from a single phone.",
        "النسخة غير متسقة؛ أعد استخراج التطبيق من هاتف واحد.",
    ),
    "INVALID_BUNDLE": Message(
        "This is not a valid AppBridge bundle.",
        "هذا ليس ملف حزمة AppBridge صالحًا.",
        "Make sure you selected the .appbridge file (or its first part .001) and all parts are present.",
        "تأكد من اختيار ملف ‎.appbridge‎ (أو الجزء الأول ‎.001‎) ومن وجود كل الأجزاء.",
    ),
    "INSTALL_FAILED_VERSION_DOWNGRADE": Message(
        "The phone has a newer version installed.",
        "الهاتف مثبت عليه إصدار أحدث.",
        "Uninstall the newer version first (its local data will be lost), or keep the newer one.",
        "أزل الإصدار الأحدث أولًا (ستُفقد بياناته المحلية)، أو احتفظ بالإصدار الأحدث.",
    ),
    "INSTALL_FAILED_UPDATE_INCOMPATIBLE": Message(
        "The installed app has a different signature.",
        "التطبيق المثبت يحمل توقيعًا مختلفًا.",
        "Uninstall the existing app first (its local data will be lost), then install again.",
        "أزل التطبيق الموجود أولًا (ستُفقد بياناته المحلية) ثم أعد التثبيت.",
    ),
    "INSTALL_FAILED_INSUFFICIENT_STORAGE": Message(
        "Not enough storage on the phone to install.",
        "مساحة الهاتف غير كافية للتثبيت.",
        "Free up space on the phone and retry.",
        "حرّر مساحة على الهاتف وأعد المحاولة.",
    ),
    "INSTALL_FAILED_DEPRECATED_SDK_VERSION": Message(
        "Android 14 blocks apps built for very old Android versions.",
        "أندرويد 14 يمنع التطبيقات المبنية لإصدارات أندرويد قديمة جدًا.",
        "AppBridge retries automatically with --bypass-low-target-sdk-block.",
        "يعيد AppBridge المحاولة تلقائيًا مع الخيار ‎--bypass-low-target-sdk-block‎.",
    ),
    "INSTALL_FAILED_NO_MATCHING_ABIS": Message(
        "This phone's processor is not supported by this app copy.",
        "معالج هذا الهاتف غير مدعوم في هذه النسخة من التطبيق.",
        "Extract the app from a phone with a similar processor (e.g. both 64-bit ARM).",
        "استخرج التطبيق من هاتف بمعالج مشابه (مثلًا كلاهما ARM 64-bit).",
    ),
    "INSTALL_FAILED_OLDER_SDK": Message(
        "The phone's Android version is too old for this app.",
        "إصدار أندرويد في الهاتف أقدم من أن يشغّل هذا التطبيق.",
        "Update the phone's Android or use another phone.",
        "حدّث نظام الهاتف أو استخدم هاتفًا آخر.",
    ),
    "INSTALL_FAILED_MISSING_SPLIT": Message(
        "Some split APK parts are missing.",
        "بعض أجزاء split APK مفقودة.",
        "Extract the app again; all split files are required.",
        "أعد استخراج التطبيق؛ كل ملفات split مطلوبة.",
    ),
    "INSTALL_FAILED_INVALID_APK": Message(
        "The APK is invalid or corrupted.",
        "ملف APK غير صالح أو تالف.",
        "Run the integrity check or extract the app again.",
        "شغّل فحص السلامة أو أعد استخراج التطبيق.",
    ),
    "INSTALL_FAILED_USER_RESTRICTED": Message(
        "The phone blocked installation over USB.",
        "منع الهاتف التثبيت عبر USB.",
        "Enable 'Install via USB' in Developer options (Xiaomi/Oppo/Vivo) and accept the prompt on the phone.",
        "فعّل «التثبيت عبر USB» من خيارات المطور (شاومي/أوبو/فيفو) واقبل النافذة على الهاتف.",
    ),
    "INSTALL_FAILED_ABORTED": Message(
        "Installation was cancelled on the phone.",
        "تم إلغاء التثبيت من الهاتف.",
        "Watch the phone screen and accept the install prompt.",
        "راقب شاشة الهاتف واقبل نافذة التثبيت.",
    ),
    "INSTALL_FAILED_VERIFICATION_FAILURE": Message(
        "Play Protect / package verification rejected the install.",
        "رفض Play Protect أو فحص الحزم التثبيت.",
        "Check the phone screen; you may need to allow the install from Play Protect.",
        "راقب شاشة الهاتف؛ قد تحتاج للسماح بالتثبيت من Play Protect.",
    ),
    "INSTALL_FAILED_DUPLICATE_PERMISSION": Message(
        "Another installed app declares the same permission.",
        "تطبيق آخر مثبت يعرّف نفس الصلاحية.",
        "Uninstall the conflicting app and retry.",
        "أزل التطبيق المتعارض وأعد المحاولة.",
    ),
    "INSTALL_FAILED": Message(
        "The installation failed.",
        "فشل التثبيت.",
        "See the details below and export the logs if it keeps happening.",
        "راجع التفاصيل أدناه وصدّر السجلات إذا تكررت المشكلة.",
    ),
}


@dataclass
class _Rule:
    pattern: re.Pattern
    code: str
    extra: dict = field(default_factory=dict)


_RULES: list[_Rule] = [
    _Rule(re.compile(r"device unauthorized|unauthorized", re.I), "DEVICE_UNAUTHORIZED"),
    _Rule(re.compile(r"device offline|error: closed|protocol fault", re.I), "DEVICE_OFFLINE"),
    _Rule(
        re.compile(r"device '.*' not found|no devices/emulators found|device not found|no devices found", re.I),
        "DEVICE_NOT_FOUND",
    ),
    _Rule(re.compile(r"No space left on device|ENOSPC", re.I), "DEVICE_STORAGE_FULL"),
    _Rule(re.compile(r"INSTALL_FAILED_VERSION_DOWNGRADE", re.I), "INSTALL_FAILED_VERSION_DOWNGRADE"),
    _Rule(
        re.compile(r"INSTALL_FAILED_UPDATE_INCOMPATIBLE|INSTALL_FAILED_SHARED_USER_INCOMPATIBLE", re.I),
        "INSTALL_FAILED_UPDATE_INCOMPATIBLE",
    ),
    _Rule(
        re.compile(r"INSTALL_FAILED_INSUFFICIENT_STORAGE|not enough space", re.I),
        "INSTALL_FAILED_INSUFFICIENT_STORAGE",
    ),
    _Rule(re.compile(r"INSTALL_FAILED_DEPRECATED_SDK_VERSION", re.I), "INSTALL_FAILED_DEPRECATED_SDK_VERSION"),
    _Rule(re.compile(r"INSTALL_FAILED_NO_MATCHING_ABIS", re.I), "INSTALL_FAILED_NO_MATCHING_ABIS"),
    _Rule(re.compile(r"INSTALL_FAILED_OLDER_SDK", re.I), "INSTALL_FAILED_OLDER_SDK"),
    _Rule(
        re.compile(r"INSTALL_FAILED_MISSING_SPLIT|INSTALL_PARSE_FAILED_.*SPLIT", re.I), "INSTALL_FAILED_MISSING_SPLIT"
    ),
    _Rule(
        re.compile(
            r"INSTALL_FAILED_INVALID_APK|INSTALL_PARSE_FAILED_NOT_APK|INSTALL_PARSE_FAILED_NO_CERTIFICATES|"
            r"INSTALL_PARSE_FAILED_UNEXPECTED_EXCEPTION|INSTALL_PARSE_FAILED_BAD_MANIFEST|"
            r"INSTALL_PARSE_FAILED_INCONSISTENT_CERTIFICATES",
            re.I,
        ),
        "INSTALL_FAILED_INVALID_APK",
    ),
    _Rule(re.compile(r"INSTALL_FAILED_USER_RESTRICTED", re.I), "INSTALL_FAILED_USER_RESTRICTED"),
    _Rule(re.compile(r"INSTALL_FAILED_ABORTED", re.I), "INSTALL_FAILED_ABORTED"),
    _Rule(re.compile(r"INSTALL_FAILED_VERIFICATION_FAILURE", re.I), "INSTALL_FAILED_VERIFICATION_FAILURE"),
    _Rule(re.compile(r"INSTALL_FAILED_DUPLICATE_PERMISSION", re.I), "INSTALL_FAILED_DUPLICATE_PERMISSION"),
    _Rule(re.compile(r"INSTALL_FAILED|INSTALL_PARSE_FAILED|Failure \[", re.I), "INSTALL_FAILED"),
]


def classify(output: str, default: str = "UNKNOWN") -> str:
    """Map raw adb/pm output to an error code."""
    text = output or ""
    for rule in _RULES:
        if rule.pattern.search(text):
            return rule.code
    return default


def is_device_gone(output: str) -> bool:
    return classify(output) in {"DEVICE_OFFLINE", "DEVICE_NOT_FOUND"}


def describe(code: str, detail: str = "", **params) -> dict:
    msg = MESSAGES.get(code) or MESSAGES["UNKNOWN"]
    return {
        "code": code,
        "detail": (detail or "")[-2000:],
        "params": params,
        "message": {"en": msg.en, "ar": msg.ar},
        "hint": {"en": msg.hint_en, "ar": msg.hint_ar},
    }


def from_exception(exc: BaseException) -> dict:
    if isinstance(exc, AppBridgeError):
        return exc.to_dict()
    if isinstance(exc, OSError) and (exc.errno == 28 or getattr(exc, "winerror", None) in (39, 112)):
        return describe("PC_DISK_FULL", str(exc))
    return describe("UNKNOWN", f"{type(exc).__name__}: {exc}")
