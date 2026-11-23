"""Map inertia (viewer/inertia.js): a quick drag keeps gliding after release.

The glide's direction and speed must come from the same recent movement.
OpenSeadragon's built-in "flick" takes direction from only the last 50 ms
sample but smooths speed over several, so a drag that pauses just before
release glides backward (seen Nov. 22, 2026, in 2 of 8 test drags). These
tests pin down glide() on synthetic pointer samples, then drive real mouse
drags in the viewer (needs the repo served on 127.0.0.1:8000, as the other
viewer checks do; skipped otherwise)."""

import urllib.request

import pytest

from pixelphilly.projection import REPO_ROOT

VIEWER = "http://127.0.0.1:8000/viewer/index.html?live=off&weather=off"


@pytest.fixture(scope="module")
def browser():
    # One Playwright for the whole module: a second sync_playwright() inside
    # the first one fails
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def js(browser):
    src = (REPO_ROOT / "viewer" / "inertia.js").read_text()
    page = browser.new_page()
    page.set_content("<html></html>")
    page.add_script_tag(content=src + "\nwindow.I = { glide, MOMENTUM_S, MIN_SPEED, MAX_GLIDE_PX }; window.__ready = true;",
                        type="module")
    page.wait_for_function("window.__ready === true")
    yield lambda expr, arg=None: page.evaluate(f"(arg) => {{ const I = window.I; {expr} }}", arg)
    page.close()


def _drag(x_per_ms, ms=100, step=10, x0=800.0):
    """Synthetic samples of a steady drag: [t, x, y] every `step` ms."""
    return [[t, x0 + x_per_ms * t, 450.0] for t in range(0, ms + 1, step)]


def test_steady_drag_glides_the_same_way(js):
    # 3 px/ms to the left = 3,000 px/s: glide is momentum x velocity
    got = js("return [I.glide(arg, 100), I.MOMENTUM_S];", _drag(-3))
    (dx, dy), momentum = got
    assert dx == pytest.approx(-3000 * momentum) and dy == pytest.approx(0)


def test_pause_before_release_means_no_glide(js):
    # The bug: drag left, hold still 150 ms (still reporting the same spot), release.
    # No glide at all (not a backward one)
    samples = _drag(-3) + [[180, 500.0, 450.0], [250, 501.0, 450.0]]
    assert js("return I.glide(arg, 250);", samples) is None
    assert js("return I.glide(arg, 250);", _drag(-3)) is None  # last movement 150 ms before release


def test_slow_drag_does_not_glide(js):
    assert js("return [I.glide(arg, 100), I.MIN_SPEED];", _drag(-0.05))[0] is None  # 50 px/s


def test_glide_is_capped(js):
    dx, dy = js("return I.glide(arg, 100);", _drag(-40))  # a 40,000 px/s jitter
    assert abs(dx) == pytest.approx(js("return I.MAX_GLIDE_PX;"))


def test_direction_uses_recent_movement_only(js):
    # Moved right long ago, then left quickly in the last 100 ms: glide goes left
    samples = [[0, 0.0, 450.0], [200, 600.0, 450.0]] + [[200 + t, 600.0 - 3 * t, 450.0] for t in range(10, 101, 10)]
    dx, _ = js("return I.glide(arg, 300);", samples)
    assert dx < 0


def test_too_few_samples(js):
    assert js("return [I.glide([], 0), I.glide([[0, 1, 1]], 0)];") == [None, None]


# --- the real viewer -----------------------------------------------------------

def _server_up():
    try:
        return urllib.request.urlopen(VIEWER, timeout=2).status == 200
    except OSError:
        return False


CENTER_X = """(() => { const v = OpenSeadragon.getViewer(document.getElementById('map')); const it = v.world.getItemAt(0);
  const z = it.viewportToImageZoom(v.viewport.getZoom(true));
  return it.viewportToImageCoordinates(v.viewport.getCenter(false)).x * z; })()"""


def _mouse_drag(page, pause_ms=0, steps=6, step_ms=16):
    page.mouse.move(800, 450)
    page.mouse.down()
    for k in range(1, steps + 1):
        page.wait_for_timeout(step_ms)
        page.mouse.move(800 - 300 * k / steps, 450)
    # A flick lets go right after the last move; a held drag waits first
    if pause_ms:
        page.wait_for_timeout(pause_ms)
    page.mouse.up()
    page.wait_for_timeout(1400)


@pytest.mark.skipif(not _server_up(), reason="needs the repo served on 127.0.0.1:8000")
@pytest.mark.parametrize("reduced", [False, True])
def test_viewer_drags(browser, reduced):
    page = browser.new_page(viewport={"width": 1600, "height": 900},
                            reduced_motion="reduce" if reduced else "no-preference")
    page.goto(VIEWER)
    page.wait_for_function("!!OpenSeadragon.getViewer(document.getElementById('map')).world.getItemAt(0)")
    page.wait_for_timeout(2500)
    fast, paused, slow = [], [], []
    for _ in range(5):
        x0 = page.evaluate(CENTER_X); _mouse_drag(page); fast.append(page.evaluate(CENTER_X) - x0)
        x0 = page.evaluate(CENTER_X); _mouse_drag(page, pause_ms=200); paused.append(page.evaluate(CENTER_X) - x0)
    x0 = page.evaluate(CENTER_X); _mouse_drag(page, steps=60, step_ms=60); slow.append(page.evaluate(CENTER_X) - x0)
    page.close()
    # Dragging 300 px left moves the view center 300 px right
    if reduced:
        assert all(abs(d - 300) < 3 for d in fast + paused + slow), (fast, paused, slow)
    else:
        assert all(d > 330 for d in fast), fast             # every quick drag glides on, never back
        assert all(abs(d - 300) < 3 for d in paused), paused  # a pause before release: no glide
        assert all(abs(d - 300) < 3 for d in slow), slow
