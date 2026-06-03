
#include "DQM/inc/DqmMetrics.hh"
#include "TH1D.h"
#include <iomanip>
#include <iostream>

int mu2e::DqmMetrics::stm(TDirectory& dir){
  TH1D* hh;

  hh = (TH1D*)dir.Get("Ver");
  addMean(hh,"stm", "gen", "version",20,0);
  
  return 0;
}
