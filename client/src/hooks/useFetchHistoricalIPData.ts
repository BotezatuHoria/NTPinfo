import { useState } from "react"
import axios from "axios"
import { NTPData } from "../utils/types.ts"
import { transformJSONDataToNTPData } from "../utils/transformJSONDataToNTPData.ts"

/**
 * Performs a GET request for the historical data for a specific server in between two chosen time stamps
 * /measurements/history/?server=${query}&start=${startDate}&end=${endDate}, where
 * server is the one provided by the user
 * startDate the start time from when the measurements were taken
 * endDate the end time until when the measurements were taken
 * The dates should be provided in ISO 8601 format
 * Each data point received is transformed to an NTPData data point
 * @param endpoint the link to the endpoint that will provide the data: under the form
 * @returns the data, loading and error status, and a function to call the GET
 */
export const useFetchHistoricalIPData = () => {
    const [data, setData] = useState<NTPData[] | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<Error | null>(null)

    const fetchData = async (endpoint: string) => {
        // console.log(`Making API call to: ${endpoint}`);
        setLoading(true)
        setError(null)
        try {
            const resp = await axios.get(endpoint);
            // console.log(`API call successful, received ${resp.data?.measurements?.length || 0} measurements`);
            const measurements = resp.data?.measurements || []
            const transformedData = measurements.map((d: any) => transformJSONDataToNTPData(d))
            setData(transformedData)
            return transformedData
        } catch (err: any) {
            // console.error(`API call failed:`, err.message);
            setError(err)
            return null
        } finally {
            setLoading(false)
        }
    }

    return {data, loading, error, fetchData}
};