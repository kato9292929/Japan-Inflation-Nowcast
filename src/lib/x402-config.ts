import type { Network } from "@x402/core/types";

// 402とdiscoveryで同じ設定を参照する。既存JINの経路・既定値を維持する。
export const SOLANA_NETWORK: Network = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp";
export const PAY_TO = process.env.X402_RECIPIENT ?? "4s8XQC2WzRfgH8Xiep7ybnCW11VKRCMwxQF6jknx3VPf";
export const USDC_ASSET = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";
export const PUBLIC_BASE_URL = (process.env.PUBLIC_BASE_URL ?? "https://jin.x402jp.com").replace(/\/$/, "");
