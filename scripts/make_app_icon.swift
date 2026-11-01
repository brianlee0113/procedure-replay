// Draws the Firsthand app icon (Figma "Brand — Firsthand" page, Icon / A · Viewfinder) as a 1024 px PNG.
// Square and opaque: iOS rounds the corners itself. Geometry is the Figma SVG's, on a 180-unit grid.
// Run: swift scripts/make_app_icon.swift ios/ProcedureReplay/Assets.xcassets/AppIcon.appiconset/AppIcon.png

import AppKit

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.png"
let px = 1024
let k = CGFloat(px) / 180

let ink = CGColor(srgbRed: 0.04, green: 0.05, blue: 0.06, alpha: 1)  // Glass (A) text/primary, Theme.swift Color.ink
let blue = CGColor(srgbRed: 0.16, green: 0.38, blue: 1.0, alpha: 1)  // Glass (A) ai, Theme.swift Color.ai

let ctx = CGContext(data: nil, width: px, height: px, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
// SVG coordinates have y down.
ctx.translateBy(x: 0, y: CGFloat(px))
ctx.scaleBy(x: k, y: -k)

ctx.setFillColor(ink)
ctx.fill(CGRect(x: 0, y: 0, width: 180, height: 180))

// Four corner brackets: the view through the glasses.
let brackets = CGMutablePath()
func bracket(_ a: CGPoint, _ corner: CGPoint, _ b: CGPoint, _ c1: CGPoint, _ c2: CGPoint) {
  brackets.move(to: a)
  brackets.addLine(to: c1)
  brackets.addQuadCurve(to: c2, control: corner)
  brackets.addLine(to: b)
}
bracket(CGPoint(x: 42, y: 72), CGPoint(x: 42, y: 42), CGPoint(x: 72, y: 42), CGPoint(x: 42, y: 54), CGPoint(x: 54, y: 42))
bracket(CGPoint(x: 108, y: 42), CGPoint(x: 138, y: 42), CGPoint(x: 138, y: 72), CGPoint(x: 126, y: 42), CGPoint(x: 138, y: 54))
bracket(CGPoint(x: 42, y: 108), CGPoint(x: 42, y: 138), CGPoint(x: 72, y: 138), CGPoint(x: 42, y: 126), CGPoint(x: 54, y: 138))
bracket(CGPoint(x: 108, y: 138), CGPoint(x: 138, y: 138), CGPoint(x: 138, y: 108), CGPoint(x: 126, y: 138), CGPoint(x: 138, y: 126))
ctx.addPath(brackets)
ctx.setStrokeColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 1))
ctx.setLineWidth(11)
ctx.setLineCap(.round)
ctx.setLineJoin(.round)
ctx.strokePath()

// The blue dot: where the expert is looking.
ctx.setFillColor(blue)
ctx.fillEllipse(in: CGRect(x: 75, y: 75, width: 30, height: 30))

let rep = NSBitmapImageRep(cgImage: ctx.makeImage()!)
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
print("wrote \(out)")
