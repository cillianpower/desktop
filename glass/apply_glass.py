"""Adds Liquid Glass window materials to Zen.

    python3 apply_glass.py <zen-desktop checkout>

Run after `npm run import`, then `npm run ffprefs` to regenerate prefs. It
edits prefs/zen/macos.yaml and engine/widget/cocoa/nsCocoaWindow.mm (on top of
Zen's own nsCocoaWindow patch); `npm run export widget/cocoa/nsCocoaWindow.mm`
turns the engine change back into Zen's patch file.

zen.widget.macos.window-material gains two values:
  8  Liquid Glass (NSGlassEffectView, regular style)
  9  Liquid Glass, clear style
"""

import os
import sys


def replace_once(src: str, old: str, new: str) -> str:
    if src.count(old) != 1:
        sys.exit(f"expected exactly one match for:\n{old}")
    return src.replace(old, new)


root = sys.argv[1]
yaml_path = os.path.join(root, "prefs/zen/macos.yaml")
mm_path = os.path.join(root, "engine/widget/cocoa/nsCocoaWindow.mm")

yaml = open(yaml_path).read()
if "Liquid Glass" not in yaml:
    yaml = replace_once(
        yaml,
        "# 7. underlay\n",
        "# 7. underlay\n"
        "# 8. Liquid Glass (macOS 26+, otherwise underlay)\n"
        "# 9. Liquid Glass, clear style (macOS 26+, otherwise underlay)\n",
    )
    open(yaml_path, "w").write(yaml)

src = open(mm_path).read()
if "ZenWindowGlassView" in src:
    sys.exit("nsCocoaWindow.mm already has the glass change")

src = replace_once(
    src,
    """static void ZenWindowVibrancyPrefChanged(const char* aPref, void* aClosure) {""",
    """static constexpr uint32_t kZenWindowMaterialGlass = 8;
static constexpr uint32_t kZenWindowMaterialClearGlass = 9;

static bool ZenWindowMaterialIsGlass() {
  uint32_t material = StaticPrefs::zen_widget_macos_window_material();
  return material == kZenWindowMaterialGlass ||
         material == kZenWindowMaterialClearGlass;
}

API_AVAILABLE(macos(26.0))
@interface ZenWindowGlassView : NSGlassEffectView {
  // NSGlassEffectView's own private subviews, which are not window content.
  NSArray<NSView*>* mGlassSubviews;
}
- (void)prefChanged;
- (NSArray<NSView*>*)windowContentSubviews;
@end

static void ZenWindowGlassPrefChanged(const char* aPref, void* aClosure) {
  if (@available(macOS 26.0, *)) {
    [static_cast<ZenWindowGlassView*>(aClosure) prefChanged];
  }
}

@implementation ZenWindowGlassView
- (instancetype)initWithFrame:(NSRect)aRect {
  self = [super initWithFrame:aRect];
  mGlassSubviews = [self.subviews copy];
  self.tintColor = [NSColor clearColor];
  [self prefChanged];
  Preferences::RegisterCallback(ZenWindowGlassPrefChanged,
                                "zen.widget.macos.window-material"_ns, self);
  return self;
}

- (void)dealloc {
  Preferences::UnregisterCallback(ZenWindowGlassPrefChanged,
                                  "zen.widget.macos.window-material"_ns, self);
  [mGlassSubviews release];
  [super dealloc];
}

- (void)prefChanged {
  self.style = StaticPrefs::zen_widget_macos_window_material() ==
                       kZenWindowMaterialClearGlass
                   ? NSGlassEffectViewStyleClear
                   : NSGlassEffectViewStyleRegular;
}

- (NSArray<NSView*>*)windowContentSubviews {
  NSMutableArray<NSView*>* views = [[self.subviews mutableCopy] autorelease];
  [views removeObjectsInArray:mGlassSubviews];
  return views;
}
@end

static NSArray<NSView*>* ContentViewContents(NSView* aContentView) {
  if (@available(macOS 26.0, *)) {
    if ([aContentView isKindOfClass:[ZenWindowGlassView class]]) {
      return [static_cast<ZenWindowGlassView*>(aContentView)
          windowContentSubviews];
    }
  }
  return [[aContentView.subviews copy] autorelease];
}

// The view to wrap the browser window's contents in, or nil for none.
static Class ZenWindowWrapperClass() {
  if (!StaticPrefs::zen_widget_macos_window_vibrancy()) {
    return nil;
  }
  if (@available(macOS 26.0, *)) {
    if (ZenWindowMaterialIsGlass()) {
      return [ZenWindowGlassView class];
    }
  }
  return [ZenWindowMaterialView class];
}

static bool IsZenWindowWrapper(NSView* aView) {
  if ([aView isKindOfClass:[ZenWindowMaterialView class]]) {
    return true;
  }
  if (@available(macOS 26.0, *)) {
    return [aView isKindOfClass:[ZenWindowGlassView class]];
  }
  return false;
}

static bool IsZenGlassWindow(NSWindow* aWindow) {
  if (@available(macOS 26.0, *)) {
    return [aWindow.contentView isKindOfClass:[ZenWindowGlassView class]];
  }
  return false;
}

static constexpr nsLiteralCString kZenWindowWrapperPrefs[] = {
    "zen.widget.macos.window-vibrancy"_ns,
    "zen.widget.macos.window-material"_ns,
};

static void ZenWindowVibrancyPrefChanged(const char* aPref, void* aClosure) {""",
)

src = replace_once(
    src,
    """  mIsBrowserWindow = true;
  Preferences::RegisterCallback(ZenWindowVibrancyPrefChanged,
                                "zen.widget.macos.window-vibrancy", this);""",
    """  mIsBrowserWindow = true;
  for (const auto& pref : kZenWindowWrapperPrefs) {
    Preferences::RegisterCallback(ZenWindowVibrancyPrefChanged, pref, this);
  }""",
)

src = replace_once(
    src,
    """  bool wanted = StaticPrefs::zen_widget_macos_window_vibrancy();
  if (wanted ==
      [mWindow.contentView isKindOfClass:[ZenWindowMaterialView class]]) {
    return;
  }

  NSRect frame = mWindow.contentView.frame;
  NSView* wrapper = wanted ? [[ZenWindowMaterialView alloc] initWithFrame:frame]
                           : [[NSView alloc] initWithFrame:frame];""",
    """  Class wanted = ZenWindowWrapperClass();
  NSView* current = mWindow.contentView;
  if (wanted ? [current class] == wanted : !IsZenWindowWrapper(current)) {
    return;
  }

  NSRect frame = current.frame;
  NSView* wrapper = [[(wanted ?: [NSView class]) alloc] initWithFrame:frame];""",
)

src = replace_once(
    src,
    """  if (mIsBrowserWindow) {
    Preferences::UnregisterCallback(ZenWindowVibrancyPrefChanged,
                                    "zen.widget.macos.window-vibrancy", this);
  }""",
    """  if (mIsBrowserWindow) {
    for (const auto& pref : kZenWindowWrapperPrefs) {
      Preferences::UnregisterCallback(ZenWindowVibrancyPrefChanged, pref, this);
    }
  }""",
)

src = replace_once(
    src,
    """  mWindow.contentView = wrapper;
  [wrapper release];
""",
    """  mWindow.contentView = wrapper;
  [wrapper release];

  // Unlike NSVisualEffectView, NSGlassEffectView can only refract what is
  // really behind it, so a glass window must be clear for the desktop to show
  // through. Otherwise restore the opaque background browser windows start
  // with.
  bool glass = IsZenGlassWindow(mWindow);
  mWindow.opaque = !glass;
  mWindow.backgroundColor =
      glass ? NSColor.clearColor : NSColor.windowBackgroundColor;
""",
)

# Gecko syncs a browser window's transparency from its root frame, which asks
# for opaque; keep glass windows clear.
src = replace_once(
    src,
    """  BOOL isTransparent = aMode == TransparencyMode::Transparent;""",
    """  BOOL isTransparent =
      aMode == TransparencyMode::Transparent || IsZenGlassWindow(mWindow);""",
)

old = """- (NSArray<NSView*>*)contentViewContents {
  return [[self.contentView.subviews copy] autorelease];
}"""
if src.count(old) != 2:
    sys.exit("expected two contentViewContents implementations")
src = src.replace(
    old,
    """- (NSArray<NSView*>*)contentViewContents {
  return ContentViewContents(self.contentView);
}""",
)

open(mm_path, "w").write(src)
print("applied")
