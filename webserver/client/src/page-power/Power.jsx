import React, { useEffect, useState } from "react";
import './Power.css';
import Sophie from "./Sophie1.svg";
import SVGDiagram from "./SVGDiagram";
import BatteryGauge from "react-battery-gauge";
import { fetchFromServer } from '../utils/api';


console.log("Power component loaded")

function Power() {
  let [data, setData] = useState({});
  const getData = () => {
    fetchFromServer('/data/power')
      .then(function (myJson) {
        setData(myJson)
      })
      .catch(function (error) {
        console.error('Error fetching power data:', error);
        // Set some default data so the page doesn't crash
        setData({});
      });
  }


  useEffect(() => {
    const interval = setInterval(() => {
      getData();

    }, 1000);  // 1000 ms = 1 second
    return () => clearInterval(interval);
  }, [])

  return (

    <div className="Power">

      <SVGDiagram
        filename={Sophie}
        var1={data.var1}
        var2={data.var2}
        var3={data.var3}
        var4={data.var4}
        var5={data.var5}
        var6={data.var6}
        var7={data.var7}
        var8={data.var8}
        var9={data.var9}
        var10={data.var10}
        var11={data.var11}
        var12={data.var12}
        var13={data.var13}
        var14={data.var14}
        var15={data.var15}
        var16={data.var16}
        var17={data.var17}
        var18={data.var18}
        var19={data.var19}
        var20={data.var20}

      >
      <div className="battery">
        <BatteryGauge
          value={data.battery_percent}
          size={150}
          padding={5}
          aspectRatio={0.52}
        />
      </div>

      </SVGDiagram>
    </div>
  )
}

export default Power;
