/**
 * Power formatting shared by the Internet and Debug pages.
 *
 * It lives here rather than in a page because the owner's rule is "show all
 * power in watts" everywhere, and the Internet page and the Debug page both
 * render the same sysfs field. Two copies of the conversion would be two
 * places to forget it.
 */

/**
 * USB bMaxPower in watts. sysfs reports the DECLARED maximum in mA at 5 V
 * ("100mA"), which is a ceiling the device is allowed to draw, not a
 * measurement -- so this is rendered with "up to". Socket 3 measured ~1 W
 * powered and idle against a 500 mA declaration, so the gap is large.
 *
 * Returns '' for anything that is not an mA reading, including the empty
 * string sysfs gives for an absent device, so callers can concatenate it
 * without a guard.
 */
export const maxWatts = (maxPower) => {
  const match = /^(\d+)\s*mA$/i.exec((maxPower || '').trim());
  if (!match) return '';
  return `up to ${(Number(match[1]) * 5 / 1000).toFixed(1)} W`;
};

/**
 * The same value with the raw sysfs reading kept alongside it, for the
 * diagnostic page. The watts are what the owner asked to see; the mA figure is
 * the literal attribute value, which is what `lsusb -v` and the journal print
 * and therefore what you compare against when something looks wrong.
 */
export const maxWattsDetailed = (maxPower) => {
  const watts = maxWatts(maxPower);
  if (!watts) return '';
  return `${watts} (${(maxPower || '').trim()})`;
};
