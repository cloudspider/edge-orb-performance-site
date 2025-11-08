## Chromedriver location
```
/Users/guy/.wdm/drivers/chromedriver/mac64
```

## Installation and Debugging

Looks like the chromedriver binary itself isn’t in that directory—only the license files remain—which explains why Selenium can’t start it. Let’s refresh the cask so we get a clean, notarized binary in place:

Reinstall the Homebrew cask (this redownloads the bundle):

brew reinstall --cask chromedriver --no-quarantine
(--no-quarantine helps avoid Gatekeeper prompts.)

Verify the binary is back:

ls -l /opt/homebrew/Caskroom/chromedriver/*/chromedriver-mac-arm64/chromedriver
You should now see an executable file in that path.

Ensure the environment points to it (if you haven’t already):

export PATH="/opt/homebrew/bin:$PATH"
export CHROMEDRIVER_PATH="/opt/homebrew/bin/chromedriver"
Add those to ~/.zshrc if you want them permanent.

If macOS still complains the first time you run it, clear the quarantine flag on the real binary:

xattr -d com.apple.quarantine /opt/homebrew/Caskroom/chromedriver/*/chromedriver-mac-arm64/chromedriver
Finally, rerun your script:

python3 scripts/tv_downloader.py
That should let Selenium attach to the Homebrew-installed chromedriver without the service error. Let me know if the reinstall still leaves the binary missing.





xattr saying “No such xattr” means there isn’t a quarantine flag on that chromedriver—so Gatekeeper isn’t blocking it anymore. At this point:

Confirm the driver is visible on your PATH and via the env var (the command you highlighted is handy):

WHICH_DRIVER=$(which chromedriver)
echo "chromedriver is at $WHICH_DRIVER"
If that prints /opt/homebrew/bin/chromedriver, you’re set. If it’s blank, make sure you ran:

export PATH="/opt/homebrew/bin:$PATH"
export CHROMEDRIVER_PATH="/opt/homebrew/bin/chromedriver"
(Add those to ~/.zshrc if you want them to persist.)

Run the script again:

python3 scripts/tv_downloader.py
Choose a chart and see if it attaches cleanly. With the quarantine removed and the env vars set, Selenium should find and launch the Homebrew chromedriver.


## Build tv_downloader

```
    ./tv_downloader/build.sh  
```