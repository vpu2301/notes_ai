"""Subjects, greetings, dates and plain-text bodies for account mail.

Same split marketing-service uses: the HTML prose lives in whole,
per-language template files so a proofreader who does not read Python can
check the German and Ukrainian; everything that has to be *computed* —
subject lines, a greeting that changes with whether we know a name, a
formatted timestamp — lives here.

The plain-text alternates use ``str.format`` rather than Jinja, and that
is not an oversight: Jinja's autoescaping would turn the ``&`` in a URL
query string into ``&amp;`` inside a text/plain part, where it is not
markup and the link would arrive broken.

Dates are formatted by hand rather than through ``locale``: the C locale
is process-global and not thread-safe, so one request formatting a
Ukrainian date would change what every concurrent request produced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from zoneinfo import ZoneInfo

SUPPORTED_LANGS: Final[tuple[str, ...]] = ("en", "de", "uk")
DEFAULT_LANG: Final = "en"

KIND_PASSWORD_RESET: Final = "password_reset"
KIND_PASSWORD_CHANGED: Final = "password_changed"
# IDX-A3: the sign-in code and the "temporarily locked" notice. Neither
# carries a link — a code mail that trains people to click is a lure.
KIND_AUTH_CODE: Final = "auth_code"
KIND_AUTH_LOCKED: Final = "auth_locked"
# IDX-A5: the notices a person must receive when their ability to get into
# the account changes. Only `email_changed` carries a link, because it is
# the only one with something to undo — and it goes to the address that
# just LOST access, which is the whole point.
KIND_MFA_ENABLED: Final = "mfa_enabled"
KIND_MFA_DISABLED: Final = "mfa_disabled"
KIND_RECOVERY_CODE_USED: Final = "recovery_code_used"
KIND_EMAIL_CHANGED: Final = "email_changed"
KIND_ACCOUNT_DELETION: Final = "account_deletion_scheduled"
# BE-0: the two mails self-serve signup sends. Which one an address gets is
# the only thing that differs between a new address and one that already has
# an account — the HTTP response is identical for both — so the pair has to
# be read together. `signup_verify` carries a code and no link, like every
# other auth code. `signup_exists` carries a link and no code, because there
# is nothing to confirm: the account already exists, and the useful thing to
# hand somebody who just tried to create it again is the way in.
KIND_SIGNUP_VERIFY: Final = "signup_verify"
KIND_SIGNUP_EXISTS: Final = "signup_exists"
# The concierge mail (OPS-0). The only mail in this service that carries a
# password, which is why the path that sends it is a CLI an operator runs
# rather than an endpoint anyone can call.
KIND_CONCIERGE_WELCOME: Final = "concierge_welcome"
KINDS: Final[tuple[str, ...]] = (
    KIND_PASSWORD_RESET,
    KIND_PASSWORD_CHANGED,
    KIND_AUTH_CODE,
    KIND_AUTH_LOCKED,
    KIND_MFA_ENABLED,
    KIND_MFA_DISABLED,
    KIND_RECOVERY_CODE_USED,
    KIND_EMAIL_CHANGED,
    KIND_ACCOUNT_DELETION,
    KIND_SIGNUP_VERIFY,
    KIND_SIGNUP_EXISTS,
    KIND_CONCIERGE_WELCOME,
)
# The kinds whose body carries an action link (tests assert the link is in
# both parts); the auth mails are deliberately absent.
LINK_KINDS: Final[tuple[str, ...]] = (
    KIND_PASSWORD_RESET,
    KIND_PASSWORD_CHANGED,
    KIND_EMAIL_CHANGED,
    KIND_SIGNUP_EXISTS,
    KIND_CONCIERGE_WELCOME,
)


def normalise_lang(lang: str | None) -> str:
    """Coerce anything to a language we actually have templates for."""
    if not lang:
        return DEFAULT_LANG
    base = lang.strip().lower().split("-", 1)[0]
    return base if base in SUPPORTED_LANGS else DEFAULT_LANG


# ── Subjects ─────────────────────────────────────────────────────────
#
# The security-notification subject deliberately leads with the fact, not
# a question. "Was this you?" in a subject line is the exact shape of a
# phishing lure, and training users to click it is the opposite of what
# this mail is for.

SUBJECTS: Final[dict[str, dict[str, str]]] = {
    KIND_PASSWORD_RESET: {
        "en": "Reset your Notes AI password",
        "de": "Setzen Sie Ihr Notes AI-Passwort zurück",
        "uk": "Відновлення пароля Notes AI",
    },
    KIND_PASSWORD_CHANGED: {
        "en": "Your Notes AI password was changed",
        "de": "Ihr Notes AI-Passwort wurde geändert",
        "uk": "Пароль Notes AI було змінено",
    },
    # The code is NOT in the subject: notification previews on a locked
    # phone would show it to whoever is holding the device.
    KIND_AUTH_CODE: {
        "en": "Your Notes AI sign-in code",
        "de": "Ihr Notes AI-Anmeldecode",
        "uk": "Ваш код входу в Notes AI",
    },
    # Neither subject says "your code is 123456", for the reason above, and
    # neither says whether an account existed. Somebody reading a lock-screen
    # preview over a shoulder learns nothing either way.
    KIND_SIGNUP_VERIFY: {
        "en": "Confirm your email address for Notes AI",
        "de": "Bestätigen Sie Ihre E-Mail-Adresse für Notes AI",
        "uk": "Підтвердьте свою електронну адресу для Notes AI",
    },
    KIND_SIGNUP_EXISTS: {
        "en": "You already have a Notes AI account",
        "de": "Sie haben bereits ein Notes AI-Konto",
        "uk": "У вас уже є обліковий запис Notes AI",
    },
    # Says the account is ready, never that a password is inside. A
    # lock-screen preview reading "your temporary password is…" is a
    # credential on a screen somebody else can be looking at.
    KIND_CONCIERGE_WELCOME: {
        "en": "Your Notes AI account is ready",
        "de": "Ihr Notes AI-Konto ist bereit",
        "uk": "Ваш обліковий запис Notes AI готовий",
    },
    KIND_AUTH_LOCKED: {
        "en": "Your Notes AI account is temporarily locked",
        "de": "Ihr Notes AI-Konto ist vorübergehend gesperrt",
        "uk": "Ваш обліковий запис Notes AI тимчасово заблоковано",
    },
    # IDX-A5. Each states the fact plainly: somebody reading only the
    # subject line on a lock screen should already know whether to worry.
    KIND_MFA_ENABLED: {
        "en": "Two-factor authentication is on for your Notes AI account",
        "de": "Zwei-Faktor-Authentifizierung für Ihr Notes AI-Konto ist aktiv",
        "uk": "Двофакторну автентифікацію для Notes AI увімкнено",
    },
    KIND_MFA_DISABLED: {
        "en": "Two-factor authentication was turned off",
        "de": "Zwei-Faktor-Authentifizierung wurde deaktiviert",
        "uk": "Двофакторну автентифікацію вимкнено",
    },
    KIND_RECOVERY_CODE_USED: {
        "en": "A recovery code was used to sign in",
        "de": "Ein Wiederherstellungscode wurde zur Anmeldung verwendet",
        "uk": "Для входу використано код відновлення",
    },
    KIND_EMAIL_CHANGED: {
        "en": "The email address on your Notes AI account was changed",
        "de": "Die E-Mail-Adresse Ihres Notes AI-Kontos wurde geändert",
        "uk": "Адресу електронної пошти вашого Notes AI було змінено",
    },
    KIND_ACCOUNT_DELETION: {
        "en": "Your Notes AI account is scheduled for deletion",
        "de": "Ihr Notes AI-Konto ist zur Löschung vorgemerkt",
        "uk": "Ваш обліковий запис Notes AI заплановано до видалення",
    },
}


def subject_for(kind: str, lang: str) -> str:
    by_lang = SUBJECTS[kind]
    return by_lang.get(lang, by_lang[DEFAULT_LANG])


# ── Greetings ────────────────────────────────────────────────────────

_GREETING_NAMED: Final[dict[str, str]] = {
    "en": "Hello {name},",
    "de": "Hallo {name},",
    "uk": "Вітаємо, {name},",
}
_GREETING_NAMELESS: Final[dict[str, str]] = {
    "en": "Hello,",
    "de": "Hallo,",
    "uk": "Вітаємо,",
}


def greeting(lang: str, display_name: str = "") -> str:
    name = (display_name or "").strip()
    if not name:
        return _GREETING_NAMELESS.get(lang, _GREETING_NAMELESS[DEFAULT_LANG])
    template = _GREETING_NAMED.get(lang, _GREETING_NAMED[DEFAULT_LANG])
    return template.format(name=name)


# ── Timestamps ───────────────────────────────────────────────────────

_MONTHS: Final[dict[str, tuple[str, ...]]] = {
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "de": (
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ),
    # Genitive — Ukrainian dates read "5 серпня", not "5 серпень".
    "uk": (
        "січня",
        "лютого",
        "березня",
        "квітня",
        "травня",
        "червня",
        "липня",
        "серпня",
        "вересня",
        "жовтня",
        "листопада",
        "грудня",
    ),
}

_DISPLAY_ZONE: Final[dict[str, str]] = {
    "en": "Europe/Kyiv",
    "uk": "Europe/Kyiv",
    "de": "Europe/Berlin",
}


def format_moment(when: datetime, lang: str) -> str:
    """A timestamp a human can check against their own memory.

    Shown in the recipient's likely local zone with the zone named, since
    "was that me at 03:14?" is the entire question the security mail
    asks, and an answer in UTC makes it harder to answer, not easier.
    """
    zone = ZoneInfo(_DISPLAY_ZONE.get(lang, "Europe/Kyiv"))
    local = when.astimezone(zone)
    month = _MONTHS.get(lang, _MONTHS[DEFAULT_LANG])[local.month - 1]
    abbrev = local.tzname() or ""
    if lang == "uk":
        return f"{local.day} {month} {local.year}, {local:%H:%M} ({abbrev})"
    if lang == "de":
        return f"{local.day}. {month} {local.year}, {local:%H:%M} ({abbrev})"
    return f"{month} {local.day}, {local.year}, {local:%H:%M} ({abbrev})"


def minutes_label(seconds: int, lang: str) -> str:
    """ "30 minutes" / "30 Minuten" / "30 хвилин", pluralised properly."""
    minutes = max(1, round(seconds / 60))
    if lang == "de":
        return f"{minutes} Minute" if minutes == 1 else f"{minutes} Minuten"
    if lang == "uk":
        # Ukrainian needs three forms; the teens are the trap that a
        # simple `n == 1` check gets wrong (11 takes the plural).
        tail_two = minutes % 100
        tail_one = minutes % 10
        if 11 <= tail_two <= 14:
            word = "хвилин"
        elif tail_one == 1:
            word = "хвилина"
        elif 2 <= tail_one <= 4:
            word = "хвилини"
        else:
            word = "хвилин"
        return f"{minutes} {word}"
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


# ── Plain-text alternates ────────────────────────────────────────────
#
# Every mail ships both parts. A text/plain alternate is what a screen
# reader, a text-mode client, and most spam filters actually read, and a
# mail without one scores measurably worse on delivery.

_TEXT: Final[dict[tuple[str, str], str]] = {
    (KIND_PASSWORD_RESET, "en"): """\
{greeting}

Someone asked to reset the password for your Notes AI account ({email}).
If that was you, open the link below to choose a new one:

{reset_url}

The link works once and expires in {expiry_label}.

If you did not ask for this, you can ignore this email — your password
has not changed and nobody can see it. Nothing happens until the link
above is opened.

Requested: {requested_at}
{client_line}
Need help? {support_url}

— Notes AI
""",
    (KIND_PASSWORD_RESET, "de"): """\
{greeting}

Jemand hat angefordert, das Passwort für Ihr Notes AI-Konto ({email})
zurückzusetzen. Falls Sie das waren, wählen Sie über den folgenden Link
ein neues Passwort:

{reset_url}

Der Link funktioniert einmal und läuft in {expiry_label} ab.

Falls Sie das nicht angefordert haben, können Sie diese E-Mail
ignorieren — Ihr Passwort wurde nicht geändert und niemand kann es
einsehen. Es passiert nichts, solange der Link nicht geöffnet wird.

Angefordert: {requested_at}
{client_line}
Brauchen Sie Hilfe? {support_url}

— Notes AI
""",
    (KIND_PASSWORD_RESET, "uk"): """\
{greeting}

Надійшов запит на відновлення пароля до вашого облікового запису
Notes AI ({email}). Якщо це були ви, перейдіть за посиланням нижче, щоб
обрати новий пароль:

{reset_url}

Посилання діє один раз і втрачає чинність через {expiry_label}.

Якщо ви цього не робили — просто проігноруйте цей лист. Ваш пароль не
змінено, і ніхто не може його побачити. Нічого не станеться, доки
посилання вище не буде відкрито.

Запит надіслано: {requested_at}
{client_line}
Потрібна допомога? {support_url}

— Notes AI
""",
    (KIND_PASSWORD_CHANGED, "en"): """\
{greeting}

The password for your Notes AI account ({email}) was just changed.

Changed: {changed_at}
{client_line}
IF THIS WAS YOU, there is nothing to do.

IF THIS WAS NOT YOU, act now — someone else may control your account.
Open this link to sign out every device immediately and start a fresh
password reset:

{lockdown_url}

That link ends every active session, cancels any pending reset link, and
lets you set a new password yourself. It stays valid for {lockdown_expiry_label}.

Need help? {support_url}

— Notes AI
""",
    (KIND_PASSWORD_CHANGED, "de"): """\
{greeting}

Das Passwort für Ihr Notes AI-Konto ({email}) wurde soeben geändert.

Geändert: {changed_at}
{client_line}
WAREN SIE DAS, müssen Sie nichts tun.

WAREN SIE DAS NICHT, handeln Sie jetzt — möglicherweise hat jemand
anderes Zugriff auf Ihr Konto. Öffnen Sie diesen Link, um sofort alle
Geräte abzumelden und eine neue Passwortzurücksetzung zu starten:

{lockdown_url}

Der Link beendet alle aktiven Sitzungen, verwirft ausstehende
Zurücksetzungs-Links und lässt Sie selbst ein neues Passwort setzen. Er
bleibt {lockdown_expiry_label} gültig.

Brauchen Sie Hilfe? {support_url}

— Notes AI
""",
    (KIND_PASSWORD_CHANGED, "uk"): """\
{greeting}

Пароль до вашого облікового запису Notes AI ({email}) щойно змінено.

Змінено: {changed_at}
{client_line}
ЯКЩО ЦЕ БУЛИ ВИ — робити нічого не потрібно.

ЯКЩО ЦЕ БУЛИ НЕ ВИ — дійте негайно, доступ до вашого облікового запису
може мати стороння особа. Відкрийте це посилання, щоб миттєво завершити
сеанси на всіх пристроях і розпочати нове відновлення пароля:

{lockdown_url}

Посилання завершує всі активні сеанси, скасовує невикористані посилання
для відновлення та дає змогу самостійно встановити новий пароль. Воно
дійсне протягом {lockdown_expiry_label}.

Потрібна допомога? {support_url}

— Notes AI
""",
    (KIND_AUTH_CODE, "en"): """\
{greeting}

Your Notes AI sign-in code:

    {code}

Enter it where you asked to sign in. It works once and expires in
{expiry_label}. Nobody from Notes AI will ever ask you for this code.

If you did not request a code, you can ignore this email — nothing
happens without it.

Requested: {requested_at}
{client_line}
— Notes AI
""",
    (KIND_AUTH_CODE, "de"): """\
{greeting}

Ihr Notes AI-Anmeldecode:

    {code}

Geben Sie ihn dort ein, wo Sie sich anmelden wollten. Er gilt einmal und
läuft in {expiry_label} ab. Niemand von Notes AI wird Sie je nach diesem
Code fragen.

Falls Sie keinen Code angefordert haben, können Sie diese E-Mail
ignorieren — ohne den Code passiert nichts.

Angefordert: {requested_at}
{client_line}
— Notes AI
""",
    (KIND_AUTH_CODE, "uk"): """\
{greeting}

Ваш код входу в Notes AI:

    {code}

Введіть його там, де ви починали вхід. Код спрацьовує один раз і діє
{expiry_label}. Ніхто з Notes AI ніколи не запитає у вас цей код.

Якщо ви не запитували код, просто проігноруйте цей лист — без коду
нічого не станеться.

Запитано: {requested_at}
{client_line}
— Notes AI
""",
    (KIND_AUTH_LOCKED, "en"): """\
{greeting}

Too many failed sign-in attempts were made on your Notes AI account, so
it is temporarily locked. You can sign in again after {locked_until}.

If this was not you, someone may be trying to guess their way in. The
lock is doing its job; you do not need to do anything. Once it lifts,
signing in with a fresh email code is all it takes.

— Notes AI
""",
    (KIND_AUTH_LOCKED, "de"): """\
{greeting}

Zu viele fehlgeschlagene Anmeldeversuche für Ihr Notes AI-Konto — es ist
vorübergehend gesperrt. Ab {locked_until} können Sie sich wieder anmelden.

Falls das nicht Sie waren, versucht womöglich jemand, sich hineinzuraten.
Die Sperre tut genau das, wofür sie da ist; Sie müssen nichts tun. Sobald
sie endet, genügt eine Anmeldung mit einem neuen E-Mail-Code.

— Notes AI
""",
    (KIND_AUTH_LOCKED, "uk"): """\
{greeting}

Забагато невдалих спроб входу до вашого облікового запису Notes AI, тому
його тимчасово заблоковано. Увійти знову можна після {locked_until}.

Якщо це були не ви, хтось, можливо, намагається підібрати вхід. Блокування
робить саме те, для чого існує; вам нічого робити не потрібно. Коли воно
завершиться, достатньо увійти з новим кодом з електронної пошти.

— Notes AI
""",
}

_CLIENT_LINE: Final[dict[str, str]] = {
    "en": "Where from: {client_label}\n",
    "de": "Woher: {client_label}\n",
    "uk": "Звідки: {client_label}\n",
}


# ── IDX-A5 notices ───────────────────────────────────────────────────
#
# Every one of these describes a change to how somebody gets into their
# account, sent to the address that would want to know. They say what
# happened, when, and what to do if it wasn't you — in that order, because
# a reader who is alarmed stops reading after the first two lines.

_TEXT_A5: Final[dict[tuple[str, str], str]] = {
    (KIND_MFA_ENABLED, "en"): """\
{greeting}

Two-factor authentication is now on for your Notes AI account. From now
on, signing in also needs a code from your authenticator app.

Keep your recovery codes somewhere safe and offline. They are the only
way back in if you lose the device — each one works once.

If this wasn't you, someone else can reach your account: change your
email password, then contact us straight away.

Changed: {changed_at}
— Notes AI
""",
    (KIND_MFA_ENABLED, "de"): """\
{greeting}

Die Zwei-Faktor-Authentifizierung für Ihr Notes AI-Konto ist jetzt aktiv.
Ab sofort benötigt die Anmeldung zusätzlich einen Code aus Ihrer
Authenticator-App.

Bewahren Sie Ihre Wiederherstellungscodes sicher und offline auf. Sie
sind der einzige Weg zurück, wenn Sie das Gerät verlieren — jeder Code
funktioniert einmal.

Falls Sie das nicht waren, hat jemand anderes Zugriff auf Ihr Konto:
Ändern Sie das Passwort Ihres E-Mail-Kontos und melden Sie sich sofort
bei uns.

Geändert: {changed_at}
— Notes AI
""",
    (KIND_MFA_ENABLED, "uk"): """\
{greeting}

Двофакторну автентифікацію для вашого Notes AI увімкнено. Відтепер для
входу також потрібен код із застосунку-автентифікатора.

Зберігайте коди відновлення в безпечному місці офлайн. Це єдиний спосіб
повернути доступ, якщо ви втратите пристрій, — кожен код спрацьовує один
раз.

Якщо це були не ви, до вашого облікового запису має доступ хтось інший:
змініть пароль поштової скриньки та одразу зв'яжіться з нами.

Змінено: {changed_at}
— Notes AI
""",
    (KIND_MFA_DISABLED, "en"): """\
{greeting}

Two-factor authentication was turned off for your Notes AI account.
{by_line}

Signing in now needs only your first factor. Your recovery codes have
been destroyed; enrolling again issues a new set.

If this wasn't you, turn two-factor back on now and change your email
password — whoever did this can sign in with one factor.

Changed: {changed_at}
— Notes AI
""",
    (KIND_MFA_DISABLED, "de"): """\
{greeting}

Die Zwei-Faktor-Authentifizierung Ihres Notes AI-Kontos wurde
deaktiviert.
{by_line}

Für die Anmeldung genügt jetzt der erste Faktor. Ihre
Wiederherstellungscodes wurden vernichtet; bei einer erneuten
Einrichtung erhalten Sie neue.

Falls Sie das nicht waren, aktivieren Sie die Zwei-Faktor-
Authentifizierung sofort wieder und ändern Sie das Passwort Ihres
E-Mail-Kontos.

Geändert: {changed_at}
— Notes AI
""",
    (KIND_MFA_DISABLED, "uk"): """\
{greeting}

Двофакторну автентифікацію для вашого Notes AI вимкнено.
{by_line}

Тепер для входу достатньо лише першого фактора. Ваші коди відновлення
знищено; після повторного налаштування ви отримаєте нові.

Якщо це були не ви, негайно увімкніть двофакторну автентифікацію знову
та змініть пароль поштової скриньки.

Змінено: {changed_at}
— Notes AI
""",
    (KIND_RECOVERY_CODE_USED, "en"): """\
{greeting}

Someone signed in to your Notes AI account with a recovery code instead
of your authenticator app. {remaining_label}

That is normal if you lost your phone and used a code from your printed
list. If it wasn't you, someone has both your first factor and your
recovery codes: sign in, regenerate your codes, and end every other
session from Settings.

Used: {used_at}
— Notes AI
""",
    (KIND_RECOVERY_CODE_USED, "de"): """\
{greeting}

Jemand hat sich bei Ihrem Notes AI-Konto mit einem
Wiederherstellungscode statt mit der Authenticator-App angemeldet.
{remaining_label}

Das ist normal, wenn Sie Ihr Telefon verloren und einen Code von Ihrer
Liste verwendet haben. Falls Sie das nicht waren, besitzt jemand sowohl
Ihren ersten Faktor als auch Ihre Wiederherstellungscodes: melden Sie
sich an, erzeugen Sie neue Codes und beenden Sie in den Einstellungen
alle anderen Sitzungen.

Verwendet: {used_at}
— Notes AI
""",
    (KIND_RECOVERY_CODE_USED, "uk"): """\
{greeting}

Хтось увійшов до вашого Notes AI за кодом відновлення, а не через
застосунок-автентифікатор. {remaining_label}

Це нормально, якщо ви втратили телефон і скористалися кодом зі свого
списку. Якщо це були не ви, хтось має і ваш перший фактор, і ваші коди
відновлення: увійдіть, згенеруйте нові коди та завершіть усі інші сеанси
в налаштуваннях.

Використано: {used_at}
— Notes AI
""",
    (KIND_EMAIL_CHANGED, "en"): """\
{greeting}

The email address on your Notes AI account was changed to
{new_email_masked}. This address can no longer be used to sign in.

If you did not do this, undo it now — the link below restores this
address, ends every signed-in session, and lets you set the account up
again:

{revert_url}

The link works for {revert_expiry_label} and once only.

Changed: {changed_at}
— Notes AI
""",
    (KIND_EMAIL_CHANGED, "de"): """\
{greeting}

Die E-Mail-Adresse Ihres Notes AI-Kontos wurde zu {new_email_masked}
geändert. Mit dieser Adresse ist keine Anmeldung mehr möglich.

Falls Sie das nicht veranlasst haben, machen Sie es jetzt rückgängig —
der Link stellt diese Adresse wieder her, beendet alle angemeldeten
Sitzungen und lässt Sie das Konto neu einrichten:

{revert_url}

Der Link gilt {revert_expiry_label} und nur einmal.

Geändert: {changed_at}
— Notes AI
""",
    (KIND_EMAIL_CHANGED, "uk"): """\
{greeting}

Адресу електронної пошти вашого Notes AI змінено на {new_email_masked}.
Ця адреса більше не дає змоги увійти.

Якщо це були не ви, скасуйте зміну зараз — посилання нижче поверне цю
адресу, завершить усі сеанси й дасть змогу налаштувати обліковий запис
заново:

{revert_url}

Посилання діє {revert_expiry_label} і спрацьовує один раз.

Змінено: {changed_at}
— Notes AI
""",
    (KIND_ACCOUNT_DELETION, "en"): """\
{greeting}

Your Notes AI account is scheduled for deletion on {purge_on}. Until
then nothing is lost, and you have been signed out everywhere.

Changed your mind? Simply sign in again before that date — signing in
cancels the deletion and restores your account exactly as it was.

After {purge_on} your account, its notes and its workspaces are removed
permanently and cannot be recovered by anyone, including us.

Requested: {requested_at}
— Notes AI
""",
    (KIND_ACCOUNT_DELETION, "de"): """\
{greeting}

Ihr Notes AI-Konto ist zur Löschung am {purge_on} vorgemerkt. Bis dahin
geht nichts verloren; Sie wurden überall abgemeldet.

Anders entschieden? Melden Sie sich einfach vor diesem Datum wieder an —
die Anmeldung bricht die Löschung ab und stellt Ihr Konto unverändert
wieder her.

Nach dem {purge_on} werden Ihr Konto, Ihre Notizen und Ihre
Arbeitsbereiche endgültig entfernt und können von niemandem
wiederhergestellt werden, auch nicht von uns.

Angefordert: {requested_at}
— Notes AI
""",
    (KIND_ACCOUNT_DELETION, "uk"): """\
{greeting}

Ваш обліковий запис Notes AI заплановано видалити {purge_on}. До того
часу нічого не втрачено, а з усіх пристроїв вас вийшло.

Передумали? Просто увійдіть знову до цієї дати — вхід скасовує видалення
й повертає обліковий запис у попередній стан.

Після {purge_on} ваш обліковий запис, нотатки та робочі простори буде
видалено назавжди, і відновити їх не зможе ніхто, зокрема ми.

Запитано: {requested_at}
— Notes AI
""",
}

_TEXT.update(_TEXT_A5)

# ── BE-0 signup ──────────────────────────────────────────────────────
#
# The pair has to read as one decision. Whoever typed the address gets a
# mail either way, and the two bodies are written so that neither confirms
# nor denies what the other one means: "confirm your address" and "you
# already have an account" are both plausible first mails to a stranger who
# mistyped their own address, and neither tells a prober anything the 202
# did not already refuse to say.
_TEXT_BE0: Final[dict[tuple[str, str], str]] = {
    (KIND_SIGNUP_VERIFY, "en"): """\
{greeting}

Confirm your email address to finish creating your Notes AI account:

    {code}

Enter it on the page that asked for it. It works once and expires in
{expiry_label}. Nobody from Notes AI will ever ask you for this code.

If you did not sign up, you can ignore this email. The account stays
unusable until somebody enters this code, and nothing has been created
in your name.

Requested: {requested_at}
{client_line}
— Notes AI
""",
    (KIND_SIGNUP_VERIFY, "de"): """\
{greeting}

Bestätigen Sie Ihre E-Mail-Adresse, um Ihr Notes AI-Konto fertigzustellen:

    {code}

Geben Sie ihn auf der Seite ein, die danach gefragt hat. Er funktioniert
einmal und läuft in {expiry_label} ab. Niemand von Notes AI wird Sie
jemals nach diesem Code fragen.

Wenn Sie sich nicht registriert haben, können Sie diese E-Mail
ignorieren. Das Konto bleibt unbenutzbar, bis jemand diesen Code
eingibt, und in Ihrem Namen wurde nichts angelegt.

Angefordert: {requested_at}
{client_line}
— Notes AI
""",
    (KIND_SIGNUP_VERIFY, "uk"): """\
{greeting}

Підтвердьте свою електронну адресу, щоб завершити створення облікового
запису Notes AI:

    {code}

Введіть його на сторінці, яка його запитала. Він працює один раз і діє
{expiry_label}. Ніхто з Notes AI ніколи не попросить у вас цей код.

Якщо ви не реєструвалися, просто проігноруйте цей лист. Обліковий запис
залишиться непридатним, доки хтось не введе цей код, і від вашого імені
нічого не створено.

Запит: {requested_at}
{client_line}
— Notes AI
""",
    (KIND_SIGNUP_EXISTS, "en"): """\
{greeting}

Somebody just tried to create a Notes AI account with this address. You
already have one, so we did not create a second — sign in instead:

{signin_url}

If you have forgotten your password, use "Forgot password?" on that page.

If this was not you, nothing has happened: no account was created, no
password was changed, and this email is the whole of it.

Requested: {requested_at}
{client_line}
— Notes AI
""",
    (KIND_SIGNUP_EXISTS, "de"): """\
{greeting}

Jemand hat gerade versucht, mit dieser Adresse ein Notes AI-Konto
anzulegen. Sie haben bereits eines, deshalb wurde kein zweites erstellt —
melden Sie sich stattdessen an:

{signin_url}

Wenn Sie Ihr Passwort vergessen haben, verwenden Sie auf dieser Seite
„Passwort vergessen?“.

Falls Sie das nicht waren, ist nichts passiert: es wurde kein Konto
angelegt, kein Passwort geändert, und diese E-Mail ist alles.

Angefordert: {requested_at}
{client_line}
— Notes AI
""",
    (KIND_SIGNUP_EXISTS, "uk"): """\
{greeting}

Хтось щойно спробував створити обліковий запис Notes AI із цією адресою.
У вас він уже є, тому другий не створювався — просто увійдіть:

{signin_url}

Якщо ви забули пароль, скористайтеся посиланням «Забули пароль?» на тій
сторінці.

Якщо це були не ви, нічого не сталося: обліковий запис не створено,
пароль не змінено, і цей лист — це все.

Запит: {requested_at}
{client_line}
— Notes AI
""",
}
_TEXT.update(_TEXT_BE0)

# ── OPS-0 concierge welcome ──────────────────────────────────────────
#
# The password is in the body and nowhere else — not in the subject, not
# in a log line, and not on the operator's screen. The mail leads with the
# change-password link rather than the password, because the first thing
# the recipient should do with a mailed credential is replace it.
_TEXT_OPS0: Final[dict[tuple[str, str], str]] = {
    (KIND_CONCIERGE_WELCOME, "en"): """\
{greeting}

Your Notes AI account is ready. Sign in with this address and the
temporary password below, then change it straight away:

{change_password_url}

Temporary password:

    {temporary_password}

It works until you change it. Treat it like any other password: nobody
from Notes AI will ever ask you for it.

Created: {created_at}
— Notes AI
""",
    (KIND_CONCIERGE_WELCOME, "de"): """\
{greeting}

Ihr Notes AI-Konto ist bereit. Melden Sie sich mit dieser Adresse und dem
untenstehenden temporären Passwort an und ändern Sie es sofort:

{change_password_url}

Temporäres Passwort:

    {temporary_password}

Es gilt, bis Sie es ändern. Behandeln Sie es wie jedes andere Passwort:
niemand von Notes AI wird Sie jemals danach fragen.

Erstellt: {created_at}
— Notes AI
""",
    (KIND_CONCIERGE_WELCOME, "uk"): """\
{greeting}

Ваш обліковий запис Notes AI готовий. Увійдіть за цією адресою та
тимчасовим паролем нижче, а потім одразу змініть його:

{change_password_url}

Тимчасовий пароль:

    {temporary_password}

Він діє, доки ви його не зміните. Ставтеся до нього як до будь-якого
іншого пароля: ніхто з Notes AI ніколи не попросить його у вас.

Створено: {created_at}
— Notes AI
""",
}
_TEXT.update(_TEXT_OPS0)


def hours_label(seconds: int, lang: str) -> str:
    """ "24 hours" / "24 Stunden" / "24 години"."""
    hours = max(1, round(seconds / 3600))
    if lang == "de":
        return f"{hours} Stunde" if hours == 1 else f"{hours} Stunden"
    if lang == "uk":
        tail_two, tail_one = hours % 100, hours % 10
        if 11 <= tail_two <= 14:
            word = "годин"
        elif tail_one == 1:
            word = "годину"
        elif 2 <= tail_one <= 4:
            word = "години"
        else:
            word = "годин"
        return f"{hours} {word}"
    return f"{hours} hour" if hours == 1 else f"{hours} hours"


def recovery_remaining_label(remaining: int, lang: str) -> str:
    """How many codes are left — or that there are none, which is urgent.

    Zero is called out rather than reported as "0 codes left", because at
    zero the user has lost their fallback and does not yet know it.
    """
    if remaining <= 0:
        return {
            "de": "Das war Ihr letzter Wiederherstellungscode. Erzeugen Sie jetzt neue — sonst kommen Sie ohne Ihr Gerät nicht mehr hinein.",
            "uk": "Це був ваш останній код відновлення. Згенеруйте нові зараз — інакше без пристрою ви не увійдете.",
        }.get(
            lang,
            "That was your last recovery code. Generate a new set now — without your device, there is no other way back in.",
        )
    if lang == "de":
        return f"Verbleibende Wiederherstellungscodes: {remaining}."
    if lang == "uk":
        return f"Залишилося кодів відновлення: {remaining}."
    return f"Recovery codes left: {remaining}."


def mfa_disabled_by_line(lang: str, *, by_admin: bool) -> str:
    """Who turned it off. An admin-initiated reset must say so plainly —
    the user did not do this and needs to know it was sanctioned."""
    if by_admin:
        return {
            "de": "Ein Administrator Ihres Arbeitsbereichs hat sie nach einer Anfrage zurückgesetzt.",
            "uk": "Адміністратор вашого робочого простору скинув її на запит.",
        }.get(lang, "An administrator of your workspace reset it after a request.")
    return {
        "de": "Sie haben diese Änderung selbst vorgenommen.",
        "uk": "Ви зробили цю зміну самостійно.",
    }.get(lang, "You made this change yourself.")


def client_line(lang: str, client_label: str) -> str:
    """One line describing the requesting client, or nothing.

    Empty when we have no usable description — an empty "Where from:"
    label reads like missing data and invites the reader to distrust the
    rest of the mail.
    """
    label = (client_label or "").strip()
    if not label:
        return ""
    return _CLIENT_LINE.get(lang, _CLIENT_LINE[DEFAULT_LANG]).format(client_label=label)


# The legal sender line every mail ends with. The HTML templates carry
# the same line in their footer.
LEGAL_LINE: Final = "3Days Labs Inc, 2166 Market Street, San Francisco, CA 94114"


def text_body(kind: str, lang: str, values: dict[str, str]) -> str:
    """Render the plain-text alternate. Raises ``KeyError`` on a gap.

    Deliberately strict: a missing variable that rendered as an empty
    string would produce a mail telling somebody to open a blank link.
    """
    template = _TEXT.get((kind, lang)) or _TEXT[(kind, DEFAULT_LANG)]
    return template.format(**values).rstrip("\n") + "\n" + LEGAL_LINE


def utcnow() -> datetime:
    return datetime.now(UTC)
