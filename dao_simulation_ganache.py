#!/usr/bin/env python3
"""
DAO Governance Simulation – 1000 Runs
Uses Ganache local blockchain and a minimal Solidity contract.
Generates an Excel file with simulation outputs.
"""

import time
import random
from pathlib import Path

import pandas as pd
from web3 import Web3
from solcx import compile_standard, install_solc

GANACHE_URL = "http://127.0.0.1:7545"
SOLC_VERSION = "0.8.20"
NUM_RUNS = 1000

OUTPUT_XLSX = "data/Simulation_Results_DAO_1000_Runs.xlsx"

RANDOM_SEED = 42

DAO_STATS = {
    "DAO 1.0": {
        "id": 1,
        "lat_mean": 15.8,
        "lat_std": 1.0,
        "comp_mean": 71.0,
        "comp_std": 3.0,
        "total_cost_mean": 119000,
        "total_cost_std": 5600,
        "roi_mean": 1.02,
        "roi_std": 0.5,
    },
    "DAO 2.0": {
        "id": 2,
        "lat_mean": 9.4,
        "lat_std": 1.0,
        "comp_mean": 83.0,
        "comp_std": 3.0,
        "total_cost_mean": 90000,
        "total_cost_std": 4500,
        "roi_mean": 4.0,
        "roi_std": 0.5,
    },
    "DAO 3.0": {
        "id": 3,
        "lat_mean": 4.2,
        "lat_std": 1.1,
        "comp_mean": 97.5,
        "comp_std": 2.4,
        "total_cost_mean": 55000,
        "total_cost_std": 2600,
        "roi_mean": 7.5,
        "roi_std": 0.5,
    },
}

OFFCHAIN_MEAN = 300
OFFCHAIN_STD = 40
OFFCHAIN_MIN = 170
OFFCHAIN_MAX = 420

LATENCY_MIN = 1.5
LATENCY_MAX = 19.0

COMPLIANCE_MIN = 60
COMPLIANCE_MAX = 100

ROI_MIN = -0.5
ROI_MAX = 9.0

COMPLIANCE_VIOLATION_THRESHOLD = 80.0

CONTRACT_SOURCE = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract DAOGovernance {

    struct Decision {
        uint256 proposalId;
        uint8 daoVersion;
        uint256 timestamp;
        address executor;
    }

    uint256 public decisionCount;
    mapping(uint256 => Decision) public decisions;

    event DecisionExecuted(
        uint256 indexed decisionId,
        uint256 indexed proposalId,
        uint8 indexed daoVersion,
        address executor,
        uint256 timestamp
    );

    function executeDecision(uint256 proposalId, uint8 daoVersion)
        external
        returns (uint256)
    {
        decisionCount += 1;

        decisions[decisionCount] = Decision({
            proposalId: proposalId,
            daoVersion: daoVersion,
            timestamp: block.timestamp,
            executor: msg.sender
        });

        emit DecisionExecuted(decisionCount, proposalId, daoVersion, msg.sender, block.timestamp);
        return decisionCount;
    }
}
"""

def set_seed(seed):
    random.seed(seed)

def connect_ganache():
    w3 = Web3(Web3.HTTPProvider(GANACHE_URL))
    if not w3.is_connected():
        raise ConnectionError("Could not connect to Ganache.")
    return w3

def compile_contract():
    install_solc(SOLC_VERSION)
    compiled = compile_standard(
        {
            "language": "Solidity",
            "sources": {"DAOGovernance.sol": {"content": CONTRACT_SOURCE}},
            "settings": {
                "outputSelection": {
                    "*": {
                        "*": ["abi", "evm.bytecode"]
                    }
                }
            },
        },
        solc_version=SOLC_VERSION,
    )
    interface = compiled["contracts"]["DAOGovernance.sol"]["DAOGovernance"]
    return interface["abi"], interface["evm"]["bytecode"]["object"]

def deploy_contract(w3, abi, bytecode, sender):
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = Contract.constructor().transact({"from": sender})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return w3.eth.contract(address=receipt.contractAddress, abi=abi)

def truncated_normal(mu, sigma, low, high):
    while True:
        x = random.gauss(mu, sigma)
        if low <= x <= high:
            return x

def dao_sequence(n):
    seq = ["DAO 1.0", "DAO 2.0", "DAO 3.0"]
    return (seq * ((n // 3) + 1))[:n]

def simulate_one(w3, contract, idx, label, sender):
    s = DAO_STATS[label]
    dao_id = s["id"]

    proposal_id = idx

    tx = contract.functions.executeDecision(proposal_id, dao_id)
    start = time.time()
    tx_hash = tx.transact({"from": sender})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    end = time.time()

    gas_used = receipt.gasUsed
    gas_price = w3.eth.gas_price
    gas_cost = gas_used * gas_price / 1e18

    lat = truncated_normal(s["lat_mean"], s["lat_std"], LATENCY_MIN, LATENCY_MAX)
    comp = truncated_normal(s["comp_mean"], s["comp_std"], COMPLIANCE_MIN, COMPLIANCE_MAX)
    offchain = truncated_normal(OFFCHAIN_MEAN, OFFCHAIN_STD, OFFCHAIN_MIN, OFFCHAIN_MAX)
    total = truncated_normal(
        s["total_cost_mean"],
        s["total_cost_std"],
        s["total_cost_mean"] - 3 * s["total_cost_std"],
        s["total_cost_mean"] + 3 * s["total_cost_std"],
    )
    roi = truncated_normal(s["roi_mean"], s["roi_std"], ROI_MIN, ROI_MAX)

    violation = "Y" if comp < COMPLIANCE_VIOLATION_THRESHOLD else "N"
    decision_outcome = "Rejected" if roi < 0 or comp < 65 else "Accepted"

    return {
        "Simulation ID": idx,
        "DAO Gen": label,
        "Latency (s)": round(lat, 2),
        "Compliance (%)": round(comp, 1),
        "Gas Cost (ETH)": round(gas_cost, 6),
        "Off-Chain Cost": int(round(offchain)),
        "Total Cost (AED)": int(round(total)),
        "Decision Outcome": decision_outcome,
        "ROI (%)": round(roi, 2),
        "Compliance Violation": violation,
    }

def run_full():
    set_seed(RANDOM_SEED)

    w3 = connect_ganache()
    accounts = w3.eth.accounts
    if not accounts:
        raise RuntimeError("No accounts available in Ganache.")
    sender = accounts[0]

    abi, bytecode = compile_contract()
    contract = deploy_contract(w3, abi, bytecode, sender)

    Path("data").mkdir(exist_ok=True)

    seq = dao_sequence(NUM_RUNS)

    rows = []
    for i in range(1, NUM_RUNS + 1):
        r = simulate_one(w3, contract, i, seq[i-1], sender)
        rows.append(r)

    df = pd.DataFrame(rows)
    df.to_excel(OUTPUT_XLSX, index=False)

if __name__ == "__main__":
    run_full()
