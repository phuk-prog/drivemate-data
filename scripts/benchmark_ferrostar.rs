use ferrostar::routing_adapters::{RouteResponseParser, osrm::OsrmResponseParser};
use serde_json::json;
use std::{error::Error, fs, path::PathBuf, time::Instant};

fn main() -> Result<(), Box<dyn Error>> {
    let directory = std::env::args().nth(1).ok_or("fixture directory required")?;
    let mut paths: Vec<PathBuf> = fs::read_dir(directory)?
        .map(|entry| entry.map(|value| value.path()))
        .collect::<Result<_, _>>()?;
    paths.retain(|path| path.to_string_lossy().ends_with(".osrm.json"));
    paths.sort();
    if paths.is_empty() { return Err("no OSRM fixtures".into()); }
    let parser = OsrmResponseParser::new(6);
    let mut results = Vec::new();
    for path in paths {
        let bytes = fs::read(&path)?;
        let mut timings = Vec::new();
        let mut accepted = false;
        let mut count = 0;
        let mut error = None;
        for _ in 0..7 {
            let started = Instant::now();
            let result = parser.parse_response(bytes.clone());
            timings.push(started.elapsed().as_secs_f64() * 1000.0);
            match result {
                Ok(routes) => { accepted = !routes.is_empty(); count = routes.len(); },
                Err(value) => { error = Some(value.to_string()); },
            }
        }
        timings.sort_by(f64::total_cmp);
        results.push(json!({"fixture": path.file_name().ok_or("missing file name")?.to_string_lossy(),
            "accepted": accepted, "routes": count, "median_ms": timings[3], "error": error}));
    }
    println!("{}", serde_json::to_string_pretty(&json!({
        "scope": "default OSRM parser compatibility; no route-following or Android claim",
        "ferrostar_source": "4e2d7f647952c0a4060efd584e6edfc6148092b9", "results": results
    }))?);
    Ok(())
}
