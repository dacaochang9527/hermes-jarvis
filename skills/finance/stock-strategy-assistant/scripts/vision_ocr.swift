import Foundation
import Vision
import AppKit

if CommandLine.arguments.count < 2 {
    fputs("usage: vision_ocr <image>\n", stderr)
    exit(2)
}
let path = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: path),
      let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let cgImage = bitmap.cgImage else {
    fputs("failed to load image\n", stderr)
    exit(1)
}
let request = VNRecognizeTextRequest { request, error in
    if let error = error {
        fputs("OCR error: \(error)\n", stderr)
        exit(1)
    }
    let observations = request.results as? [VNRecognizedTextObservation] ?? []
    for obs in observations {
        if let candidate = obs.topCandidates(3).first {
            let box = obs.boundingBox
            print(String(format: "%.3f %.3f %.3f %.3f %@", box.minX, box.minY, box.width, box.height, candidate.string))
        }
    }
}
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["zh-Hans", "en-US"]
let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("perform failed: \(error)\n", stderr)
    exit(1)
}
