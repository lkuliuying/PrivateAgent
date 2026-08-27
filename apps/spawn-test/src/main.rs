use std::process::Command;

fn main() {
    let exe = r"F:\Program\Agent\.venv\Scripts\python.exe";
    let cwd = r"F:\Program\Agent";
    match Command::new(exe)
        .args(["-X", "utf8", "-c", "print('grandchild-ok')"])
        .current_dir(cwd)
        .env_clear()
        .output()
    {
        Ok(out) => {
            println!("SPAWN_OK status={}", out.status);
            print!("STDOUT {}", String::from_utf8_lossy(&out.stdout));
        }
        Err(err) => println!("SPAWN_DENIED {err}"),
    }
}
