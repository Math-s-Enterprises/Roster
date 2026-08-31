"""The PDF attached to the owner's copy of the roster.

Verified by reading the text back OUT of the generated PDF rather than by
checking it did not raise. A file that is 2kB of valid PDF containing the
wrong week would pass the second and fail the first.
"""
import pymupdf
import pytest

from app.services.roster_pdf import build_roster_pdf

WEEK = "2026-08-31"
PEOPLE = [
    {"name": "Megan", "role": "Assistant Manager", "shifts": [
        {"day": "mon", "start": "06:00", "end": "16:00"},
        {"day": "tue", "start": "06:00", "end": "16:00"},
    ]},
    {"name": "Emma", "role": "Shop Floor", "shifts": [
        {"day": "mon", "start": "06:00", "end": "13:30"},
        {"day": "wed", "start": None, "end": None, "paid_holiday": True},
    ]},
    {"name": "Azaryia", "role": "Night Shift", "shifts": [
        {"day": "sat", "start": "23:30", "end": "07:00"},
    ]},
]


def text_of(pdf_bytes):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(page.get_text() for page in doc), doc.page_count


@pytest.fixture()
def built():
    return build_roster_pdf("Top Oil South Link", WEEK, PEOPLE)


class TestItIsAValidPdf:
    def test_it_is_a_pdf_at_all(self, built):
        assert built.startswith(b"%PDF-")

    def test_a_normal_week_is_one_page(self, built):
        assert text_of(built)[1] == 1

    def test_a_large_team_pages_rather_than_overflowing(self):
        many = [{"name": f"Person {i}", "role": "Shop Floor", "shifts": [
            {"day": "mon", "start": "09:00", "end": "17:00"}]} for i in range(60)]
        assert text_of(build_roster_pdf("Shop", WEEK, many))[1] > 1


class TestItSaysTheRightThings:
    def test_the_shop_and_the_week(self, built):
        text, _ = text_of(built)
        assert "Top Oil South Link" in text
        assert "31 Aug" in text and "6 Sep" in text and "2026" in text

    def test_everybody_is_on_it(self, built):
        text, _ = text_of(built)
        for name in ("Megan", "Emma", "Azaryia"):
            assert name in text

    def test_every_day_is_a_column_with_its_date(self, built):
        text, _ = text_of(built)
        for label in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            assert label in text
        assert "1 Sep" in text and "5 Sep" in text

    def test_the_times_are_there(self, built):
        text, _ = text_of(built)
        assert "06:00" in text and "16:00" in text and "23:30" in text

    def test_leave_is_shown(self, built):
        assert "Holiday" in text_of(built)[0]

    def test_hours_are_totalled_per_person_and_overall(self, built):
        from app.services.scheduler import paid_hours
        megan = 2 * paid_hours("06:00", "16:00", breaks_paid=False)
        text, _ = text_of(built)
        assert f"{megan:g}h" in text
        assert "3 on the rota" in text


class TestEdges:
    def test_an_empty_roster_still_produces_a_file(self):
        text, pages = text_of(build_roster_pdf("Shop", WEEK, []))
        assert pages == 1 and "0 on the rota" in text

    def test_a_broken_week_start_does_not_raise(self):
        """One bad roster must not cost the owner their copy — or, because
        the send is one call, everybody else's."""
        assert build_roster_pdf("Shop", "not-a-date", PEOPLE).startswith(b"%PDF-")

    def test_a_long_name_does_not_break_the_layout(self):
        pdf = build_roster_pdf("Shop", WEEK, [
            {"name": "Bartholomew Fitzwilliam-Montgomery", "role": "Customer Service Manager",
             "shifts": [{"day": "mon", "start": "09:00", "end": "17:00"}]}])
        assert text_of(pdf)[1] == 1


class TestItReachesTheEmail:
    """The PDF being correct is useless if it never gets attached."""

    def _captured(self, monkeypatch, pdf_fails=False):
        """Run the real send with the HTTP call replaced, and keep the body."""
        import asyncio, base64
        from app.services import mailer

        seen = {}

        class FakeResponse:
            status_code = 200
            def raise_for_status(self): return None

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None, json=None):
                seen.update(json or {})
                return FakeResponse()

        monkeypatch.setattr(mailer, "enabled", True)
        monkeypatch.setattr(mailer.httpx, "AsyncClient", lambda **k: FakeClient())
        # A no-op that is still awaitable. Patching it with something that
        # itself calls asyncio.sleep recurses forever, which is what the
        # first version of this harness did.
        async def _no_wait(*_a, **_k):
            return None
        monkeypatch.setattr(mailer.asyncio, "sleep", _no_wait)
        if pdf_fails:
            import app.services.roster_pdf as rp
            monkeypatch.setattr(
                rp, "build_roster_pdf",
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

        result = asyncio.run(
            mailer.send_shop_roster(
                "Top Oil", WEEK, PEOPLE, [{"name": "Boss", "email": "b@x.ie"}]))
        return seen, result

    def test_the_pdf_is_attached_and_is_a_pdf(self, monkeypatch):
        import base64
        sent, result = self._captured(monkeypatch)
        assert result["sent"], result
        assert sent["attachments"], "no attachment reached the request"
        one = sent["attachments"][0]
        assert one["filename"] == f"roster-{WEEK}.pdf"
        assert base64.b64decode(one["content"]).startswith(b"%PDF-")

    def test_a_pdf_failure_still_sends_the_email(self, monkeypatch):
        """A missing attachment is a nuisance. A rota nobody receives is the
        thing this whole feature exists to prevent."""
        sent, result = self._captured(monkeypatch, pdf_fails=True)
        assert result["sent"], "the email was lost because the PDF failed"
        assert "attachments" not in sent
