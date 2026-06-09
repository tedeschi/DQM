
#include "DQM/inc/DqmMetrics.hh"
#include "TH1D.h"
#include <iomanip>
#include <iostream>

int mu2e::DqmMetrics::stm(TDirectory& dir){
  TH1D* hh;

  hh = (TH1D*)dir.Get("Ver");
  addMean(hh,"stm", "gen", "version",20,0);

  hh = (TH1D*)dir.Get("RawADCHPGe");
  addMean(hh,"stm","digi","meanADCHPGe",20,2);
  addRMS(hh,"stm","digi", "rmsADCHPGe", 20,2);

  hh = (TH1D*)dir.Get("RawADCLaBr");
  addMean(hh,"stm","digi","meanADCLaBr",20,2);
  addRMS(hh,"stm","digi", "rmsADCLaBr", 20,2);

  
  return 0;
}
