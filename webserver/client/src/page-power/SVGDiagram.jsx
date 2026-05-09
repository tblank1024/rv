import React, { useEffect, useState } from "react";
import SVG from 'react-inlinesvg';


function SVGDiagram(props) {
    let {filename, var1, var2, var3, var4, var5, var6, var7, var8, var9, var10, 
        var11, var12, var13, var14, var15, var16, var17, var18, var19, var20,
        children } = props
    let [originalSvgText, setOriginalSvgText] = useState(null);
    let [processedSvg, setProcessedSvg] = useState(null);

    let replacements = [
        ["{var1}", var1],
        ["{var2}", var2],
        ["{var3}", var3],
        ["{var4}", var4],
        ["{var5}", var5],
        ["{var6}", var6],
        ["{var7}", var7],
        ["{var8}", var8],
        ["{var9}", var9],
        ["{var10}", var10],
        ["{var11}", var11],
        ["{var12}", var12],
        ["{var13}", var13],
        ["{var14}", var14],
        ["{var15}", var15],
        ["{var16}", var16],
        ["{var17}", var17],
        ["{var18}", var18],
        ["{var19}", var19],
        ["{var20}", var20],        
    ]

    // Fetch the original SVG text once
    useEffect(() => {
        if(originalSvgText === null) {
            fetch(filename)
                .then(r => r.text())
                .then(text => {
                    setOriginalSvgText(text)
                })
        }
    }, [filename, originalSvgText]);

    // Process replacements whenever the original SVG or variables change
    useEffect(() => {
        if(originalSvgText !== null) {
            let svg = originalSvgText;
            replacements.forEach(([from, to]) => {
                svg = svg.replace(new RegExp(from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'), to || '');
            });
            setProcessedSvg(svg);
        }
    }, [originalSvgText, var1, var2, var3, var4, var5, var6, var7, var8, var9, var10, 
        var11, var12, var13, var14, var15, var16, var17, var18, var19, var20]);

    return (
        <div className="base_svg">
            <SVG src={processedSvg} style={{width: '100%', height: 'auto', display: 'block'}}/>
            {children}
        </div>
    )
}

export default SVGDiagram;
