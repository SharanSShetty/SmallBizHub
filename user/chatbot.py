import json
import math
from datetime import datetime
from urllib import error, request

from django.conf import settings
from django.utils import timezone

from Business.models import Business, Review


GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)


def _safe_text(value):
    return (value or "").strip()


def _haversine_distance_km(lat1, lon1, lat2, lon2):
    radius = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def _matches_query(business, query_tokens):
    haystack = " ".join(
        [
            _safe_text(business.name),
            _safe_text(business.shop),
            _safe_text(business.business_type),
            _safe_text(business.business_address),
            _safe_text(business.city),
            _safe_text(business.district),
            _safe_text(business.state),
            _safe_text(business.country),
            _safe_text(business.description),
            _safe_text(business.landmark),
        ]
    ).lower()
    return sum(1 for token in query_tokens if token in haystack)


def _get_business_reviews_summary(business):
    reviews = list(
        Review.objects.filter(business=business, parent__isnull=True)
        .select_related("user")
        .prefetch_related("replies", "likes")
        .order_by("-created_at")[:3]
    )
    if not reviews:
        return "No reviews yet."

    summary_lines = []
    for review in reviews:
        reply_count = review.replies.count()
        summary_lines.append(
            f'- "{review.content[:180]}" by {review.user.username} '
            f"({review.total_likes()} likes, {reply_count} replies)"
        )
    return "\n".join(summary_lines)


def _get_hours_summary(business):
    hours = list(business.operating_hours.all())
    if not hours:
        return _safe_text(business.hours_of_operation) or "Hours not available."

    day_names = {
        0: "Monday",
        1: "Tuesday",
        2: "Wednesday",
        3: "Thursday",
        4: "Friday",
        5: "Saturday",
        6: "Sunday",
    }
    lines = []
    for entry in hours:
        if entry.is_closed:
            lines.append(f"{day_names.get(entry.day_of_week, 'Day')}: Closed")
        else:
            open_time = entry.open_time.strftime("%I:%M %p") if entry.open_time else "?"
            close_time = entry.close_time.strftime("%I:%M %p") if entry.close_time else "?"
            lines.append(f"{day_names.get(entry.day_of_week, 'Day')}: {open_time} - {close_time}")
    return "; ".join(lines)


def _is_open_now(business, now):
    hours = list(business.operating_hours.all())
    if not hours:
        return None

    weekday = now.weekday()
    current_time = now.time()
    for entry in hours:
        if entry.day_of_week != weekday:
            continue
        if entry.is_closed or not entry.open_time or not entry.close_time:
            return False
        return entry.open_time <= current_time <= entry.close_time
    return None


def _serialize_business(business, user_lat=None, user_lon=None):
    distance = None
    if (
        user_lat is not None
        and user_lon is not None
        and business.latitude is not None
        and business.longitude is not None
    ):
        distance = _haversine_distance_km(
            user_lat,
            user_lon,
            float(business.latitude),
            float(business.longitude),
        )

    now = timezone.localtime()
    is_open_now = _is_open_now(business, now)
    open_text = "Unknown"
    if is_open_now is True:
        open_text = "Open now"
    elif is_open_now is False:
        open_text = "Closed now"

    return {
        "id": business.id,
        "shop": business.shop,
        "name": business.name,
        "type": business.business_type,
        "address": business.business_address,
        "city": business.city or "",
        "district": business.district or "",
        "phone": business.mobile_number,
        "description": _safe_text(business.description) or "No description available.",
        "hours": _get_hours_summary(business),
        "status": open_text,
        "likes": business.total_likes(),
        "review_count": business.reviews.count(),
        "distance_km": round(distance, 2) if distance is not None else None,
        "social_links": [
            f"{item.platform}: {item.url}" for item in business.social_media_links.all()
        ],
        "review_summary": _get_business_reviews_summary(business),
    }


def build_chatbot_context(user, message, user_lat=None, user_lon=None):
    query_tokens = [token for token in message.lower().split() if len(token) > 2]
    approved_businesses = list(
        Business.objects.filter(approval_status=True)
        .prefetch_related("operating_hours", "social_media_links", "reviews")
        .order_by("-id")
    )

    scored = []
    for business in approved_businesses:
        score = _matches_query(business, query_tokens)
        distance = None
        if (
            user_lat is not None
            and user_lon is not None
            and business.latitude is not None
            and business.longitude is not None
        ):
            distance = _haversine_distance_km(
                user_lat,
                user_lon,
                float(business.latitude),
                float(business.longitude),
            )
            if distance <= 10:
                score += 3
            elif distance <= 25:
                score += 1
        scored.append((score, distance if distance is not None else 999999, business))

    scored.sort(key=lambda item: (-item[0], item[1], -item[2].total_likes()))
    selected_businesses = [item[2] for item in scored[:8]]

    saved_businesses = list(
        user.saved_businesses.all().prefetch_related(
            "operating_hours",
            "social_media_links",
            "reviews",
        )[:6]
    )

    top_businesses = list(
        Business.objects.filter(approval_status=True)
        .prefetch_related("operating_hours", "social_media_links", "reviews")
        .order_by("-id")[:4]
    )

    return {
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "user": {
            "username": user.username,
            "email": user.email,
            "saved_count": len(saved_businesses),
        },
        "message": message,
        "location_available": user_lat is not None and user_lon is not None,
        "selected_businesses": [
            _serialize_business(business, user_lat, user_lon)
            for business in selected_businesses
        ],
        "saved_businesses": [
            _serialize_business(business, user_lat, user_lon)
            for business in saved_businesses
        ],
        "top_businesses": [
            _serialize_business(business, user_lat, user_lon)
            for business in top_businesses
        ],
        "capabilities": [
            "search businesses by type, name, address, and area",
            "recommend nearby or relevant businesses",
            "answer questions about business details, phone numbers, hours, and social links",
            "summarize customer reviews",
            "help with saved businesses",
            "guide the user on how to use the app",
            "help the user write a support complaint when needed",
        ],
    }


def _extract_text(response_data):
    candidates = response_data.get("candidates", [])
    if not candidates:
        return None

    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if part.get("text")]
    if texts:
        return "\n".join(texts).strip()
    return None


def generate_chatbot_reply(history, context):
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("Gemini API key is missing. Set GEMINI_API_KEY in your environment.")

    guidance = """
You are the user-side assistant for Small BiZ Hub, a local business discovery app.
Only answer using the provided app context.
You help with:
- searching and recommending businesses
- comparing nearby businesses
- explaining business details, hours, phone numbers, and social links
- summarizing reviews
- helping users manage saved businesses
- onboarding and app usage help
- turning support issues into a clear complaint draft

Rules:
- Do not invent businesses or details that are not in the context.
- If the app context is missing something, say that clearly.
- Be concise, practical, and friendly.
- When recommending businesses, mention shop name and why it matches.
- For review summaries, mention overall patterns from the listed reviews.
- If the user wants support help, give a complaint draft they can paste into the contact form.
""".strip()

    contents = [
        {"role": "user", "parts": [{"text": guidance}]},
        {
            "role": "user",
            "parts": [{"text": f"App context:\n{json.dumps(context, ensure_ascii=True)}"}],
        },
    ]

    for item in history[-8:]:
        role = item.get("role")
        text = _safe_text(item.get("text"))
        if role not in {"user", "model"} or not text:
            continue
        contents.append({"role": role, "parts": [{"text": text}]})

    payload = json.dumps(
        {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.4,
                "topP": 0.9,
                "maxOutputTokens": 700,
            },
        }
    ).encode("utf-8")

    req = request.Request(
        GEMINI_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.GEMINI_API_KEY,
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini API request failed: {details or exc.reason}") from exc
    except error.URLError as exc:
        raise RuntimeError("Unable to reach Gemini API.") from exc

    response_data = json.loads(body)
    text = _extract_text(response_data)
    if not text:
        raise RuntimeError("Gemini API returned an empty response.")
    return text
